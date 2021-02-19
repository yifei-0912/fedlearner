# Copyright 2020 The FedLearner Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# coding: utf-8

import logging
from collections import OrderedDict
from contextlib import contextmanager

import tensorflow.compat.v1 as tf

import fedlearner.data_join.common as common
from fedlearner.data_join.raw_data_iter_impl.raw_data_iter import RawDataIter


class TfExampleItem(RawDataIter.Item):
    def __init__(self, record_str):
        super().__init__()
        self._record_str = record_str
        self._parse_example_error = False
        example = self._parse_example()
        dic = common.convert_tf_example_to_dict(example)
        self._features.update({key: dic[key] for key in dic
                               if key in self._allowed_fields})
        self._csv_record = None
        self._gc_example(example)

    @classmethod
    def make(cls, example_id, event_time, raw_id, fname=None, fvalue=None):
        fields = OrderedDict()
        fields["example_id"] = example_id
        fields["event_time"] = event_time
        fields["raw_id"] = raw_id
        if fname:
            assert len(fname) == len(fvalue), \
                    "Field name should match field value"
            for i, v in enumerate(fname):
                fields[v] = fvalue[i]
        ex = common.convert_dict_to_tf_example(fields)
        return cls(ex.SerializeToString())

    @property
    def example_id(self):
        res = self._features.get('example_id', common.InvalidExampleId)
        if res == common.InvalidExampleId:
            logging.warning('Note!!! return invalid example id')
        return res

    @property
    def raw_id(self):
        res = self._features.get('raw_id', common.InvalidRawId)
        if res == common.InvalidRawId:
            logging.warning('Note!!! return invalid raw id')
        return res

    @property
    def event_time(self):
        res = self._features.get('event_time', common.InvalidEventTime)
        if res == common.InvalidEventTime and 'event_time' in self._features:
            logging.warning('Note!!! return invalid event time')
        return int(res)

    @property
    def record(self):
        return self._record_str

    @property
    def tf_record(self):
        return self._record_str

    @property
    def csv_record(self):
        if self._csv_record is None:
            self._csv_record = {}
            example = self._parse_example()
            if not self._parse_example_error:
                try:
                    self._csv_record = \
                        common.convert_tf_example_to_dict(example)
                except Exception as e: # pylint: disable=broad-except
                    logging.error("Failed convert tf example to csv record, "\
                                  "reason %s", e)
            self._gc_example(example)
        return self._csv_record

    def set_example_id(self, example_id):
        example = self._parse_example()
        if example is not None:
            feat = example.features.feature
            if isinstance(example_id, str):
                example_id = example_id.encode()
            feat['example_id'].CopyFrom(tf.train.Feature(
                        bytes_list=tf.train.BytesList(value=[example_id])
                    )
                )
            self._record_str = example.SerializeToString()
            self._example_id = example_id
            if self._csv_record is not None:
                self._csv_record = None
        self._gc_example(example)

    def _parse_example(self):
        try:
            if not self._parse_example_error:
                example = tf.train.Example()
                example.ParseFromString(self._record_str)
                return example
        except Exception as e: # pylint: disable=broad-except
            logging.error("Failed parse tf.Example from record %s, reason %s",
                           self._record_str, e)
            self._parse_example_error = True
        return None

    @staticmethod
    def _gc_example(example):
        if example is not None:
            example.Clear()
            del example

    def clear(self):
        del self._record_str
        del self._csv_record


class TfRecordIter(RawDataIter):
    @classmethod
    def name(cls):
        return 'TF_RECORD'

    @contextmanager
    def _data_set(self, fpath):
        data_set = None
        expt = None
        try:
            data_set = tf.data.TFRecordDataset(
                    [fpath],
                    compression_type=self._options.compressed_type,
                    num_parallel_reads=1,
                    buffer_size=None if self._options.read_ahead_size <= 0 \
                            else self._options.read_ahead_size
                )
            batch_size = self._options.read_batch_size if \
                    self._options.read_batch_size > 0 else 1
            data_set = data_set.batch(batch_size)
            yield data_set
        except Exception as e: # pylint: disable=broad-except
            logging.warning("Failed to access file: %s, reason %s", fpath, e)
            expt = e
        if data_set is not None:
            del data_set
        if expt is not None:
            raise expt

    def _inner_iter(self, fpath):
        with self._data_set(fpath) as data_set:
            for batch in iter(data_set):
                for raw_data in batch.numpy():
                    yield TfExampleItem(raw_data)

    def _reset_iter(self, index_meta):
        if index_meta is not None:
            fpath = index_meta.fpath
            fiter = self._inner_iter(fpath)
            item = next(fiter)
            return fiter, item
        return None, None
