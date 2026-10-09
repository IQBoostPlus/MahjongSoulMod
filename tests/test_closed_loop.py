"""Regression coverage using annotated state transitions and injected clicks.

These tests never click the real desktop or claim live-game acceptance.
"""
import logging
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import numpy as np

from ai.engine import AIDecisionMaker, ActionType, GameAction, DoraCalculator, DefenseAnalysis, StrategyParams
from ai.shanten import ShantenCalculator, to_count_array
from core.context import AppContext
from core.events import EventBus, GameEvent
from game_state.tracker import GameState, GameTracker, Meld, MeldType
from vision.buttons import ButtonDetector
from vision.differ import StateDiffer, StatefulDiffer
from vision.pipeline import VisionFrame, VisionPipeline
from vision.regions import Rect
from vision.verifier import ActionVerifier
from vision.executor import VisionActionExecutor


def frame(hand=None, river=None, timestamp=1, **kwargs):
    hand = [0, 0, 0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 27, 28] if hand is None else hand
    return VisionFrame(hand_tiles=list(hand), hand_confidences=[0.9] * len(hand),
                       hand_boxes=[(30 + 25 * i, 250, 20, 40) for i in range(len(hand))],
                       discards=[river or [], [], [], []], timestamp=timestamp,
                       window_rect=(0, 0, 500, 400), **kwargs)


class ButtonEvidenceTests(unittest.TestCase):
    def test_constant_color_template_cannot_match_blank_screen(self):
        detector = self.detector()
        detector._cv_templates['ron'] = np.full((10, 10, 3), [0, 255, 0], np.uint8)
        self.assertIsNone(detector._match_opencv('ron', np.zeros((30, 30, 3), np.uint8)))

    def test_real_template_matching_positive_and_negative(self):
        detector = self.detector()
        tile = np.random.default_rng(1).integers(0, 256, (10, 10, 3), dtype=np.uint8)
        detector._cv_templates['ron'] = tile
        screen = np.zeros((40, 50, 3), np.uint8)
        self.assertIsNone(detector._match_opencv('ron', screen))
        screen[12:22, 18:28] = tile
        self.assertEqual(detector._match_opencv('ron', screen), (23, 17))

    def detector(self):
        obj = object.__new__(ButtonDetector)
        obj._has_airtest = False
        obj._has_cv = True
        obj._air_templates = {}
        obj._cv_templates = {}
        return obj

    def test_missing_templates_do_not_invent_buttons(self):
        detector = self.detector()
        self.assertEqual(detector.detect_buttons(np.zeros((120, 500, 3), np.uint8)), [])
        self.assertIsNone(detector.find_button_position('ron', None))

    def test_failed_match_does_not_use_coordinates(self):
        detector = self.detector()
        detector._cv_templates['pon'] = np.ones((10, 10, 3), np.uint8)
        with patch.object(detector, '_match_opencv', return_value=None):
            self.assertIsNone(detector.find_button_position('pon', np.zeros((30, 30, 3), np.uint8)))

    def test_positive_match_uses_actual_position(self):
        detector = self.detector()
        detector._cv_templates['ron'] = np.ones((10, 10, 3), np.uint8)
        with patch.object(detector, '_match_opencv', return_value=(12, 16)):
            self.assertEqual(detector.find_button_position('ron', np.zeros((30, 30, 3), np.uint8)), (12, 16))


class ActionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.before = frame()
        hand = list(self.before.hand_tiles)
        hand.remove(28)
        self.after = frame(hand, [28], 2)
        self.action = GameAction(ActionType.DISCARD, 28)
        self.verifier = ActionVerifier()

    def test_discard_needs_hand_and_river_identity(self):
        self.assertTrue(self.verifier._verify_outcome(self.action, self.before, self.after))
        for bad in (frame(timestamp=2), frame(self.after.hand_tiles, [], 2),
                    frame(self.after.hand_tiles, [27], 2), None, self.before):
            self.assertFalse(self.verifier._verify_outcome(self.action, self.before, bad))
        wrong_hand = list(self.before.hand_tiles)
        wrong_hand.remove(27)
        self.assertFalse(self.verifier._verify_outcome(self.action, self.before, frame(wrong_hand, [28], 2)))

    def test_missing_before_is_not_success(self):
        self.assertFalse(self.verifier._verify_outcome(self.action, None, self.after))

    def test_exact_tile_box_and_absent_tile(self):
        self.assertEqual(self.verifier._plan_target(self.action, self.before, self.before.window_rect, 0), (365, 270))
        self.assertIsNone(self.verifier._plan_target(GameAction(ActionType.DISCARD, 33), self.before, None, 0))
        self.before.hand_boxes = []
        self.assertIsNone(self.verifier._plan_target(self.action, self.before, None, 0))

    def test_unknown_or_low_confidence_hand_cannot_click(self):
        self.before.hand_tiles[0] = -1
        self.assertIsNone(self.verifier._plan_target(self.action, self.before, None, 0))
        self.before.hand_tiles[0] = 0
        self.before.hand_confidences[0] = 0.2
        self.assertIsNone(self.verifier._plan_target(self.action, self.before, None, 0))

    def test_missing_confidence_and_changed_hand_after_riichi_no_discard(self):
        self.before.hand_confidences = []
        self.assertIsNone(self.verifier._plan_target(self.action, self.before, None, 0))
        before = frame(visible_buttons=['riichi'], button_positions={'riichi': (400, 200)})
        changed = frame(timestamp=2)
        changed.hand_tiles[0] = 33
        pipeline = Mock(process_frame=Mock(return_value=changed))
        clicks = Mock(return_value=True)
        with patch('vision.verifier.time.sleep'):
            self.assertFalse(ActionVerifier(pipeline, click_fn=clicks).execute_with_verify(
                GameAction(ActionType.RIICHI, 28), before))
        self.assertEqual(clicks.call_count, 1)

    def test_button_requires_observed_position(self):
        before = frame(visible_buttons=['ron'])
        action = GameAction(ActionType.RON)
        self.assertIsNone(self.verifier._plan_target(action, before, None, 0))
        before.button_positions['ron'] = (400, 200)
        self.assertEqual(self.verifier._plan_target(action, before, None, 0), (400, 200))

    def test_retry_polls_without_reclicking(self):
        clicks = Mock(return_value=True)
        pipeline = Mock()
        pipeline.process_frame.side_effect = [frame(timestamp=2), None, self.after]
        verifier = ActionVerifier(pipeline, click_fn=clicks)
        with patch('vision.verifier.time.sleep'):
            self.assertTrue(verifier.execute_with_verify(self.action, self.before))
        self.assertEqual(clicks.call_count, 1)
        self.assertEqual(pipeline.process_frame.call_count, 3)

    def test_unconfirmed_action_clicks_once_and_returns_failure(self):
        clicks = Mock(return_value=True)
        pipeline = Mock()
        pipeline.process_frame.return_value = frame(timestamp=2)
        with patch('vision.verifier.time.sleep'):
            self.assertFalse(ActionVerifier(pipeline, click_fn=clicks).execute_with_verify(self.action, self.before))
        self.assertEqual(clicks.call_count, 1)

    def test_cancel_before_click(self):
        clicks = Mock(return_value=True)
        verifier = ActionVerifier(Mock(), click_fn=clicks, can_execute=lambda: False)
        self.assertFalse(verifier.execute_with_verify(self.action, self.before))
        clicks.assert_not_called()

    def test_cancel_during_riichi_prevents_second_click(self):
        before = frame(visible_buttons=['riichi'], button_positions={'riichi': (400, 200)})
        active = [True]
        def click(x, y):
            active[0] = False
            return True
        clicks = Mock(side_effect=click)
        pipeline = Mock(process_frame=Mock(return_value=frame(timestamp=2)))
        verifier = ActionVerifier(pipeline, click_fn=clicks, can_execute=lambda: active[0])
        with patch('vision.verifier.time.sleep'):
            self.assertFalse(verifier.execute_with_verify(GameAction(ActionType.RIICHI, 28), before))
        self.assertEqual(clicks.call_count, 1)

    def test_riichi_button_precedes_discard_and_needs_confirmation(self):
        before = frame(visible_buttons=['riichi'], button_positions={'riichi': (400, 200)})
        selected = frame(timestamp=2)
        after = frame(self.after.hand_tiles, [28], 3, riichi_sticks=1)
        pipeline = Mock()
        pipeline.process_frame.side_effect = [selected, after]
        clicks = Mock(return_value=True)
        with patch('vision.verifier.time.sleep'):
            self.assertTrue(ActionVerifier(pipeline, click_fn=clicks).execute_with_verify(GameAction(ActionType.RIICHI, 28), before))
        self.assertEqual([call.args for call in clicks.call_args_list], [(400, 200), (365, 270)])
        self.assertFalse(self.verifier._verify_outcome(GameAction(ActionType.RIICHI, 28), self.before, self.after))

    def test_win_disappearance_is_not_round_result(self):
        before = frame(visible_buttons=['tsumo'])
        self.assertFalse(self.verifier._verify_outcome(GameAction(ActionType.TSUMO), before, frame(timestamp=2)))
        self.assertTrue(self.verifier._verify_outcome(GameAction(ActionType.TSUMO), before, frame(timestamp=2, round_ended=True)))

    def test_missing_window_no_click(self):
        pipeline = Mock(running=True)
        executor = VisionActionExecutor(pipeline)
        with patch.object(executor, '_human_delay'), patch.object(executor, '_find_window', return_value=None), patch.object(executor, '_click_at') as click:
            self.assertFalse(executor.execute(self.action))
        click.assert_not_called()

    def test_capture_exception_disables_executor(self):
        pipeline = Mock(running=True)
        pipeline.process_frame.side_effect = RuntimeError('capture failed')
        executor = VisionActionExecutor(pipeline)
        with patch.object(executor, '_human_delay'), patch.object(executor, '_find_window', return_value=self.before.window_rect):
            self.assertFalse(executor.execute(self.action))
        self.assertFalse(executor._enabled)

    def test_unconfirmed_action_preserves_observation_evidence(self):
        pipeline = Mock(process_frame=Mock(return_value=None))
        verifier = ActionVerifier(pipeline, click_fn=Mock(return_value=True))
        with patch('vision.verifier.time.sleep'):
            self.assertFalse(verifier.execute_with_verify(self.action, self.before))
        self.assertEqual(verifier.last_failure['before_hand'], self.before.hand_tiles)
        self.assertIsNone(verifier.last_failure['after_hand'])


class DifferTests(unittest.TestCase):
    def test_stable_transition_emits_once_and_noise_is_ignored(self):
        differ = StatefulDiffer(confirmation_frames=2)
        start = frame([0] * 13)
        differ.diff(start)
        self.assertIn('new_round', [e.event_type for e in differ.diff(start)])
        noise = frame([0] * 13 + [1], timestamp=2)
        self.assertEqual(differ.diff(noise), [])
        differ.diff(start)
        differ.diff(start)
        differ.diff(noise)
        events = differ.diff(noise)
        self.assertEqual([e.data['tile'] for e in events if e.event_type == 'draw_tile'], [1])
        self.assertEqual(differ.diff(noise), [])

    def test_repeated_discard_not_lost(self):
        differ = StateDiffer()
        differ.diff(frame([0] * 13, [4]))
        events = differ.diff(frame([0] * 13, [4, 4], 2))
        self.assertEqual([e.data['tile'] for e in events if e.event_type == 'discard_tile'], [4])

    def test_open_hand_draw(self):
        differ = StateDiffer()
        differ.diff(frame([0] * 10))
        events = differ.diff(frame([0] * 10 + [9], timestamp=2))
        self.assertEqual([e.data['tile'] for e in events if e.event_type == 'draw_tile'], [9])

    def test_win_opportunity_not_reported_as_result(self):
        differ = StateDiffer()
        differ.diff(frame([0] * 13))
        events = differ.diff(frame([0] * 13, timestamp=2, visible_buttons=['ron']))
        self.assertIn('agari_available', [e.event_type for e in events])
        self.assertNotIn('hu', [e.event_type for e in events])

    def test_unchanged_start_hand_is_not_new_round(self):
        differ = StateDiffer()
        before = frame([0] * 13)
        differ.diff(before)
        self.assertEqual(differ.diff(before), [])


class RuleTests(unittest.TestCase):
    complete = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 27, 27]

    def test_riichi_discards_exact_red_draw(self):
        state = GameState(last_action='draw', last_draw_tile=34, available_actions=set())
        player = state.players[0]
        player.hand = self.complete[:-1] + [34]
        player.is_liqi = True
        self.assertEqual(AIDecisionMaker().decide_discard(state).tile, 34)
        state.last_draw_tile = 33
        self.assertEqual(AIDecisionMaker().decide_discard(state).action, ActionType.NONE)

    def test_complete_shape_without_win_opportunity_still_discards(self):
        state = GameState(left_tiles=50, available_actions=set())
        state.players[0].hand = list(self.complete)
        action = AIDecisionMaker().decide_discard(state)
        self.assertIn(action.action, (ActionType.DISCARD, ActionType.RIICHI))
        self.assertIn(action.tile, state.players[0].hand)

    def test_red_fives_count_like_normal(self):
        self.assertEqual(to_count_array([4, 34, 13, 35, 22, 36]), to_count_array([4, 4, 13, 13, 22, 22]))
        red = list(self.complete)
        red[4] = 34
        self.assertEqual(ShantenCalculator.calculate(red), -1)

    def test_quad_not_two_seven_pairs(self):
        self.assertEqual(ShantenCalculator._chiitoi_shanten(to_count_array([0]*4 + [9]*2 + [18]*2 + [27]*2 + [28]*2 + [29]*2)), 1)

    def test_complete_hand_does_not_declare_riichi(self):
        state = GameState(left_tiles=50)
        state.players[0].hand = list(self.complete)
        self.assertEqual(AIDecisionMaker().decide_discard(state).action, ActionType.NONE)

    def test_riichi_discard_preserves_tenpai(self):
        state = GameState(left_tiles=50)
        state.players[0].hand = self.complete[:-1] + [28]
        ai = AIDecisionMaker()
        ai.params.aggression = 1
        action = ai.decide_discard(state)
        self.assertEqual(action.action, ActionType.RIICHI)
        remainder = list(state.players[0].hand)
        remainder.remove(action.tile)
        self.assertEqual(ShantenCalculator.calculate(remainder), 0)
        self.assertTrue(ShantenCalculator.get_waiting_tiles(to_count_array(remainder)))

    def test_open_hand_and_four_melds(self):
        self.assertEqual(ShantenCalculator.calculate([27], 4), 0)
        self.assertEqual(ShantenCalculator.calculate([27, 27], 4), -1)
        self.assertEqual(ShantenCalculator.get_waiting_tiles(to_count_array([27]), 4), [27])
        self.assertEqual(ShantenCalculator.calculate(self.complete[3:], 1), -1)

    def test_open_player_cannot_riichi_or_chi_wrong_seat(self):
        state = GameState(left_tiles=50, last_discard_seat=1)
        state.players[0].is_menzen = False
        state.players[0].hand = [0, 1, 2, 3, 4, 5, 9, 10, 11, 27, 28]
        state.players[0].melds = [Meld(MeldType.PON, [18]*3, 1)]
        ai = AIDecisionMaker()
        self.assertFalse(ai._should_riichi(state))
        self.assertEqual(ai.decide_call(state, 2, 'chi').action, ActionType.PASS)

    def test_honor_dora_cycles(self):
        self.assertEqual(DoraCalculator.indicator_to_dora(30), 27)
        self.assertEqual(DoraCalculator.indicator_to_dora(33), 31)
        self.assertEqual(DoraCalculator.count_dora_in_hand([4, 34], [3]), 3)

    def test_red_and_normal_five_share_defense_risk(self):
        state = GameState()
        state.players[1].is_liqi = True
        state.players[1].discards = [34]
        defense = DefenseAnalysis(StrategyParams())
        risks = defense.get_risks_for_hand(state, [4, 34])
        self.assertEqual(risks[4], risks[34])
        self.assertLess(risks[34], 0.1)

    def test_open_kan_removes_three_and_closed_kan_stays_closed(self):
        tracker = GameTracker()
        tracker.state.players[0].hand = [4, 4, 34, 9]
        tracker.on_game_event('kan', {'seat': 0, 'tile': 4})
        self.assertEqual(tracker.state.players[0].hand, [9])
        tracker = GameTracker()
        tracker.state.players[0].hand = [4, 4, 4, 34, 9]
        tracker.on_game_event('an_kan', {'seat': 0, 'tile': 4})
        self.assertTrue(tracker.state.players[0].is_menzen)
        self.assertEqual(tracker.state.players[0].hand, [9])

    def test_added_kan_upgrades_existing_meld(self):
        tracker = GameTracker()
        player = tracker.state.players[0]
        player.melds = [Meld(MeldType.PON, [4]*3, 1)]
        player.hand = [34, 9]
        tracker.on_game_event('add_kan', {'seat': 0, 'tile': 34})
        self.assertEqual(len(player.melds), 1)
        self.assertEqual(player.hand, [9])
        self.assertEqual(player.melds[0].type, MeldType.KAN_JIA)

    def test_own_discard_not_counted_twice(self):
        tracker = GameTracker()
        tracker.on_game_event('new_round', {'tiles': [4, 34]})
        tracker.on_game_event('discard_tile', {'seat': 0, 'tile': 4})
        self.assertEqual(tracker.state.get_seen_count(4), 2)


class PipelineTests(unittest.TestCase):
    def test_missing_capture_is_not_cached_success(self):
        pipeline = VisionPipeline(Mock(), Mock(), Mock(), Mock())
        pipeline._last_frame = frame()
        pipeline._capture.capture.return_value = None
        self.assertIsNone(pipeline.process_frame())

    def test_window_roi_offsets_applied_to_tile_and_button(self):
        raw = np.zeros((500, 700, 3), np.uint8)
        regions = SimpleNamespace(hand=Rect(.1, .5, .8, .9), draw_tile=Rect(.8, .5, .9, .9),
                                  dora=Rect(.1, .1, .2, .2), buttons=Rect(.5, .3, .9, .5),
                                  get_discard_rect=lambda seat: Rect(.1, .1, .2, .2))
        tiles = Mock(is_ready=True, hand_boxes=[(10, 20, 20, 40)])
        tiles.recognize_hand.return_value = [(4, .9)]
        tiles.recognize_river.return_value = []
        tiles.recognize_dora.return_value = []
        buttons = Mock(BUTTON_NAMES=['ron'])
        buttons.find_button_position.return_value = (12, 14)
        pipeline = VisionPipeline(Mock(capture=Mock(return_value=raw)), regions, tiles, buttons)
        pipeline.set_window_rect(100, 50, 500, 400)
        result = pipeline.process_frame()
        self.assertEqual(result.hand_boxes, [(160, 270, 20, 40)])
        self.assertEqual(result.button_positions['ron'], (362, 184))


class ContextTests(unittest.TestCase):
    def context(self):
        ctx = object.__new__(AppContext)
        ctx._running = ctx._auto_mode = True
        ctx._listen_only = False
        ctx._vision_pipeline = None
        ctx._ai = Mock()
        ctx._event_bus = EventBus()
        ctx._executor = Mock()
        ctx._tracker = SimpleNamespace(state=GameState(in_game=True, available_actions={'tsumo'}))
        return ctx

    def test_failed_action_pauses_auto(self):
        ctx = self.context()
        ctx._executor.execute.return_value = False
        ctx._on_ai_decision(GameEvent.AI_DECISION, {'action': GameAction(ActionType.DISCARD, 4)})
        self.assertFalse(ctx._auto_mode)
        ctx._executor.set_enabled.assert_called_with(False)
        ctx._on_ai_decision(GameEvent.AI_DECISION, {'action': GameAction(ActionType.DISCARD, 4)})
        self.assertEqual(ctx._executor.execute.call_count, 1)

    def test_executor_exception_pauses_auto(self):
        ctx = self.context()
        ctx._executor.execute.side_effect = RuntimeError('click failed')
        ctx._on_ai_decision(GameEvent.AI_DECISION, {'action': GameAction(ActionType.DISCARD, 4)})
        self.assertFalse(ctx._auto_mode)
        ctx._executor.set_enabled.assert_called_with(False)

    def test_only_own_completed_call_triggers_discard(self):
        ctx = self.context()
        state = GameState(in_game=True, last_action='call', last_action_seat=0, available_actions=set())
        state.players[0].melds = [Meld(MeldType.PON, [9]*3, 1)]
        state.players[0].hand = [0]*11
        ctx._ai.decide_discard.return_value = GameAction(ActionType.DISCARD, 0)
        ctx._on_call_completed(GameEvent.PON, {'state': state})
        ctx._ai.decide_discard.assert_called_once_with(state)
        state.last_action_seat = 1
        ctx._on_call_completed(GameEvent.PON, {'state': state})
        self.assertEqual(ctx._ai.decide_discard.call_count, 1)

    def test_tracker_call_event_reaches_discard_once(self):
        ctx = self.context()
        tracker = GameTracker()
        tracker.state.in_game = True
        tracker.state.players[0].hand = [4, 4, 0, 1, 2, 6, 7, 8, 9, 10, 11, 27, 28]
        ctx._tracker = tracker
        ctx._ai.decide_discard.return_value = GameAction(ActionType.DISCARD, 28)
        tracker.add_callback(ctx._on_tracker_update)
        ctx._event_bus.subscribe(GameEvent.PON, ctx._on_call_completed)
        tracker.on_game_event('pon', {'seat': 0, 'tile': 4, 'from': 3})
        self.assertEqual(len(tracker.state.players[0].hand), 11)
        ctx._ai.decide_discard.assert_called_once_with(tracker.state)
        tracker.on_game_event('pon', {'seat': 1, 'tile': 9, 'from': 2})
        self.assertEqual(ctx._ai.decide_discard.call_count, 1)

    def test_open_draw_triggers_decision(self):
        ctx = self.context()
        state = GameState(in_game=True, last_action='draw', available_actions=set())
        state.players[0].melds = [Meld(MeldType.PON, [9]*3, 1)]
        state.players[0].hand = [0]*11
        ctx._ai.decide_discard.return_value = GameAction(ActionType.DISCARD, 0)
        ctx._on_draw_tile(GameEvent.DRAW_TILE, {'state': state})
        ctx._ai.decide_discard.assert_called_once_with(state)

    def test_win_only_from_confirmed_opportunity(self):
        ctx = self.context()
        ctx._ai.decide_agari.return_value = GameAction(ActionType.TSUMO)
        ctx._on_agari_available(GameEvent.AGARI_AVAILABLE, {'zimo': True})
        ctx._ai.decide_agari.assert_called_once()
        ctx._tracker.state.available_actions = set()
        ctx._on_agari_available(GameEvent.AGARI_AVAILABLE, {'zimo': True})
        self.assertEqual(ctx._ai.decide_agari.call_count, 1)


if __name__ == '__main__':
    unittest.main()
