# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Collection of evaluator combinators.

This module exports common evaluator types which are used to compose multiple
specific evaluators. Use these combinators to compose a single evaluator from
multiple specific evaluator implementations, to be used when calling
dashboard.dashboard.pinpoint.model.task.Evalute(...).

Also in this module are common filters/predicates that are useful in composing
FilteringEvaluator instances that deal with tasks and events. Filters are
callables that return a boolean while Evaluators are callables that return an
iterable of actions (or None).
"""
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

import itertools

##### Filters #####
###################


class Not(object):

  def __init__(self, filter_):
    self._filter = filter_

  def __call__(self, *args):
    return not self._filter(*args)


class All(object):

  def __init__(self, *filters):
    self._filters = filters

  def __call__(self, *args):
    return all(f(*args) for f in self._filters)


class Any(object):

  def __init__(self, *filters):
    self._filters = filters

  def __call__(self, *args):
    return any(f(*args) for f in self._filters)


class TaskTypeEq(object):

  def __init__(self, task_type_filter):
    self._task_type_filter = task_type_filter

  def __call__(self, task, *_):
    return task.task_type == self._task_type_filter


class TaskStatusIn(object):

  def __init__(self, include_types):
    self._include_types = include_types

  def __call__(self, task, *_):
    return task.status in self._include_types


class TaskIsEventTarget(object):

  def __call__(self, task, event, _):
    return event.target_task is None or event.target_task == task.id


##### Evaluators #####
######################


class NoopEvaluator(object):

  def __call__(self, *_):
    return None


class TaskPayloadLiftingEvaluator(object):
  """An evaluator that copies task payload and status to the accumulator.

  A common pattern in evaluators in Pinpoint is lifting, or copying, the task's
  payload into the accumulator potentially after changes to the task's
  in-memory payload has been made. This evaluator can be sequenced before or
  after other evaluators to copy the payload of a task to the accumulator.

  Side-effects:

    - Copies the payload and status of a task into an entry in the accumulator
      keyed by the task's id.

    - The status of the task becomes an entry in the dict with the key 'status'
      as if it was part of the task's payload.

  Returns None.
  """

  def __init__(self, exclude_keys=None, exclude_event_types=None):
    self._exclude_keys = exclude_keys or {}
    self._exclude_event_types = exclude_event_types or {}

  def __call__(self, task, event, accumulator):
    if event.type in self._exclude_event_types:
      return None

    update = {
        key: val
        for key, val in task.payload.items()
        if key not in self._exclude_keys
    }
    update['status'] = task.status
    accumulator.update({task.id: update})
    return None


class SequenceEvaluator(object):

  def __init__(self, evaluators):
    if not evaluators:
      raise ValueError('Argument `evaluators` must not be empty.')

    self._evaluators = evaluators

  def __call__(self, task, event, accumulator):

    def Flatten(seqs):
      return list(itertools.chain(*seqs))

    return Flatten([
        evaluator(task, event, accumulator) or []
        for evaluator in self._evaluators
    ])


class FilteringEvaluator(object):

  def __init__(self, predicate, delegate, alternative=None):
    if not predicate:
      raise ValueError('Argument `predicate` must not be empty.')
    if not delegate:
      raise ValueError('Argument `delegate` must not be empty.')

    self._predicate = predicate
    self._delegate = delegate
    self._alternative = alternative or NoopEvaluator()

  def __call__(self, *args):
    if self._predicate(*args):
      return self._delegate(*args)
    return self._alternative(*args)


class DispatchByEventTypeEvaluator(object):

  def __init__(self, evaluator_map, default_evaluator=None):
    if not evaluator_map and not default_evaluator:
      raise ValueError(
          'Either one of evaluator_map or default_evaluator must be provided.')

    self._evaluator_map = evaluator_map
    self._default_evaluator = default_evaluator or NoopEvaluator

  def __call__(self, task, event, accumulator):
    handler = self._evaluator_map.get(event.type, self._default_evaluator)
    return handler(task, event, accumulator)


class Selector(FilteringEvaluator):

  def __init__(self, task_type=None, event_type=None, predicate=None):

    def Predicate(task, event, accumulator):
      matches = False
      if task_type is not None:
        matches |= task_type == task.task_type
      if event_type is not None:
        matches |= event_type == event.type
      if predicate is not None:
        matches |= predicate(task, event, accumulator)
      return matches

    super(Selector, self).__init__(
        predicate=Predicate, delegate=TaskPayloadLiftingEvaluator())
