"""
雀魂 MITM 代理插件 - 独立文件 (mitmdump -s addon.py)

工作原理:
  1. mitmproxy 拦截雀魂的 WebSocket 流量
  2. 解码 liqi protobuf 消息 → 重建牌局状态
  3. AI 引擎决策 → 写入动作到 action_queue.json
  4. 主程序读取动作队列并执行鼠标点击
"""

import json, os, struct, time
from pathlib import Path


# ── 配置 ──
ACTION_QUEUE = os.path.join(str(Path.home()), ".majsoul_automod", "action_queue.json")
EVENT_LOG = os.path.join(str(Path.home()), ".majsoul_automod", "events.log")
os.makedirs(os.path.dirname(ACTION_QUEUE), exist_ok=True)


# ═══════════════════════════════════════════════
# 1. 牌编码工具
# ═══════════════════════════════════════════════

SUIT_NAMES = {0: "m", 1: "p", 2: "s", 3: "z"}

def tile_str(t):
    if t < 0 or t > 36: return "?"
    s = (t // 9) if t < 34 else ((t - 34) // 9)
    v = (t % 9 + 1) if t < 34 else ((t - 34) % 9 + 1)
    r = "r" if t >= 34 else ""
    return f"{v}{SUIT_NAMES.get(s, '?')}{r}"

def hand_str(tiles):
    return ",".join(tile_str(t) for t in tiles)

SUITS_MAN = range(0, 9)
SUITS_PIN = range(9, 18)
SUITS_SOU = range(18, 27)
YAOCHU = {0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33}


# ═══════════════════════════════════════════════
# 2. 协议解码器
# ═══════════════════════════════════════════════

def find_json_str(data, pos=0):
    """在 bytes 中查找 JSON 字符串起始位置"""
    markers = [b'{"', b'[{']
    results = []
    for m in markers:
        p = data.find(m, pos)
        if p >= 0: results.append(p)
    return min(results) if results else -1

def try_parse_json(data):
    """尝试从 bytes 中解析 JSON"""
    try:
        s = data.decode('utf-8', errors='replace').lstrip('\x00')
        return json.loads(s)
    except:
        return None

def try_decode_protobuf(data):
    """简易 protobuf 解码 - 提取字符串字段"""
    result = {}
    pos = 0
    strings = []
    while pos < len(data):
        if data[pos] == 0x0a:  # string field
            pos += 1
            strlen, n = _varint(data, pos)
            pos = n
            if pos + strlen <= len(data):
                s = data[pos:pos+strlen].decode('utf-8', errors='replace')
                if s.startswith('.lq.'):
                    result['name'] = s
                elif len(s) > 2:
                    strings.append(s)
                pos += strlen
            else: break
        elif data[pos] == 0x12:  # bytes field
            pos += 1
            strlen, n = _varint(data, pos)
            pos = n
            result['data'] = data[pos:pos+strlen] if pos+strlen <= len(data) else b''
            pos += strlen if pos+strlen <= len(data) else 0
        else:
            pos += 1
    if strings:
        result['strings'] = strings
    return result

def _varint(data, pos):
    value = 0; shift = 0
    while pos < len(data):
        b = data[pos]
        value |= (b & 0x7f) << shift
        shift += 7; pos += 1
        if (b & 0x80) == 0: break
    return value, pos

def decode_wrapper(data):
    """解码 Wrapper 消息: 2字节长度 + protobuf"""
    if len(data) < 2: return None
    msg_len = struct.unpack('<H', data[:2])[0]
    if msg_len <= 0 or msg_len + 2 > len(data): return None
    return try_decode_protobuf(data[2:2+msg_len])

def decode_hand_tiles(data):
    """从 new_round 消息中提取手牌"""
    # 遍历所有 varint 提取牌 ID(0-36)
    tiles = []
    pos = 0
    while pos < len(data):
        tag = data[pos]; pos += 1
        wire = tag & 0x07
        if wire == 0:  # varint
            val, pos = _varint(data, pos)
            if 0 <= val <= 36:
                tiles.append(val)
        elif wire == 2:  # length-delimited
            strlen, pos = _varint(data, pos)
            pos += strlen
        elif wire == 5:  # 32-bit
            pos += 4
        else:
            break
    # 过滤出合理的牌(前13-14枚是手牌)
    hand = [t for t in tiles if 0 <= t <= 36]
    return hand[:14] if len(hand) >= 13 else []


# ═══════════════════════════════════════════════
# 3. 牌局追踪器
# ═══════════════════════════════════════════════

class GameTracker:
    """对局状态追踪"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.in_game = False
        self.seat = 0
        self.hand = []
        self.scores = [25000]*4
        self.deposits = [0]*4
        self.round_wind = 0
        self.round_num = 0
        self.honba = 0
        self.dealer = 0
        self.left_tiles = 70
        self.dora = -1
        self.last_action = ""
        self.seen = [0]*37
        # 玩家状态
        self.players = [{'discards':[], 'melds':[], 'liqi':False, 'score':25000}
                        for _ in range(4)]

    def add_tile(self, t):
        if 0 <= t < 37: self.seen[t] += 1

    def remaining(self, t):
        return 4 - (self.seen[t] if 0 <= t < 37 else 0)

    def on_new_round(self, data):
        self.reset()
        self.in_game = True
        # 从 protobuf 里提取手牌
        hand = decode_hand_tiles(data)
        if hand:
            self.hand = hand
            for t in hand: self.add_tile(t)
        ctx.log.info(f"[MOD] New round - hand({len(hand)}): {hand_str(self.hand[:5])}...")
        self._log_event("new_round", {"hand_count": len(self.hand)})

    def on_draw(self, tile):
        if tile >= 0:
            self.hand.append(tile)
            self.add_tile(tile)
            ctx.log.info(f"[MOD] Draw: {tile_str(tile)} → {len(self.hand)} tiles")

    def on_discard(self, seat, tile, moqie=False):
        if tile >= 0:
            self.players[seat]['discards'].append(tile)
            self.add_tile(tile)
            if seat == self.seat and tile in self.hand:
                self.hand.remove(tile)
        if seat == self.seat:
            ctx.log.info(f"[MOD] Self discard: {tile_str(tile)}")
            self._trigger_ai()

    def _trigger_ai(self):
        """触发 AI 决策 - 写入动作队列"""
        if len(self.hand) <= 0:
            return
        decision = self._ai_decide()
        with open(ACTION_QUEUE, 'w') as f:
            json.dump(decision, f)

    def _ai_decide(self):
        """AI 决策引擎(简版 向听数计算)"""
        if not self.hand: return {"action": "pass"}
        hand = self.hand[:]
        best = self._evaluate(hand)
        return {
            "action": "discard",
            "tile": best,
            "tile_str": tile_str(best),
            "hand": hand_str(hand),
            "hand_count": len(hand),
            "timestamp": time.time()
        }

    def _evaluate(self, hand):
        """选择要切的牌 - 向听数优先"""
        from collections import Counter
        best_score = -999
        best_tile = hand[0]

        for tile in set(hand):
            new_hand = hand.copy()
            new_hand.remove(tile)
            shanten = self._calc_shanten(new_hand)
            score = -shanten * 10
            # 安全度
            safety = self.remaining(tile)
            score += safety
            if score > best_score:
                best_score = score
                best_tile = tile
        return best_tile

    def _calc_shanten(self, hand):
        """向听数计算"""
        counts = [0]*34
        for t in hand:
            if 0 <= t < 34: counts[t] += 1

        def normal_shanten(counts, total):
            needed = total // 3
            best = 999
            for i in range(34):
                if counts[i] < 2: continue
                counts[i] -= 2
                s = _calc_mentsu(counts, needed, 0, 0)
                counts[i] += 2
                if s < best: best = s
            if best == 999:
                best = _calc_mentsu(counts, needed, 0, 0) + 1
            return best

        def _calc_mentsu(counts, target, melds, partials):
            if melds > target: return 999
            if partials > target - melds: partials = target - melds
            if all(c == 0 for c in counts):
                s = 2*(target-melds)-partials-1
                return -1 if s < -1 else s
            pos = next(i for i in range(34) if counts[i] > 0)
            best = 999
            c = counts[pos]

            if pos < 27 and pos % 9 < 7 and counts[pos]>0 and counts[pos+1]>0 and counts[pos+2]>0:
                counts[pos]-=1; counts[pos+1]-=1; counts[pos+2]-=1
                s = _calc_mentsu(counts, target, melds+1, partials)
                counts[pos]+=1; counts[pos+1]+=1; counts[pos+2]+=1
                if s < best: best = s

            if c >= 3:
                counts[pos]-=3; s = _calc_mentsu(counts, target, melds+1, partials)
                counts[pos]+=3
                if s < best: best = s
            if c >= 2:
                counts[pos]-=2; s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=2
                if s < best: best = s
            if pos < 27 and pos%9<8 and counts[pos]>0 and counts[pos+1]>0:
                counts[pos]-=1; counts[pos+1]-=1
                s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=1; counts[pos+1]+=1
                if s < best: best = s
            if pos < 27 and pos%9<7 and counts[pos]>0 and counts[pos+2]>0:
                counts[pos]-=1; counts[pos+2]-=1
                s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=1; counts[pos+2]+=1
                if s < best: best = s

            counts[pos] = 0
            s = _calc_mentsu(counts, target, melds, partials)
            counts[pos] = c
            if s < best: best = s
            return best

        total = len(hand)
        return normal_shanten(counts, total)

    def _log_event(self, event_type, data=None):
        try:
            with open(EVENT_LOG, 'a') as f:
                f.write(json.dumps({"t": time.time(), "e": event_type, "d": data}) + '\n')
        except: pass


# ═══════════════════════════════════════════════
# 4. 日志工具 (不依赖 mitmproxy ctx)
# ═══════════════════════════════════════════════

_log_file = os.path.join(str(Path.home()), ".majsoul_automod", "logs", "addon.log")
os.makedirs(os.path.dirname(_log_file), exist_ok=True)

def log_info(msg):
    try:
        from mitmproxy import ctx
        ctx.log.info(msg)
    except:
        pass
    try:
        with open(_log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except:
        pass


# ═══════════════════════════════════════════════
# 5. mitmproxy 插件入口
# ═══════════════════════════════════════════════

class MajsoulAddon:
    def __init__(self):
        self.tracker = GameTracker()
        log_info("[MOD] Addon loaded — waiting for WebSocket traffic...")

    def websocket_message(self, flow):
        if not flow.messages: return
        msg = flow.messages[-1]
        if msg.from_client: return  # 只处理服务端消息

        data = msg.content
        if not data or len(data) < 4: return

        try:
            wrapper = decode_wrapper(data)
            if not wrapper or 'name' not in wrapper: return

            name = wrapper['name']
            payload = wrapper.get('data', b'')

            if 'NotifyNewRound' in name:
                self.tracker.on_new_round(payload)
            elif 'NotifyDrawTile' in name:
                tiles = decode_hand_tiles(payload)
                if tiles: self.tracker.on_draw(tiles[-1])
            elif 'NotifyDiscardTile' in name:
                tiles = decode_hand_tiles(payload)
                seat = next((t for t in tiles if 0 <= t <= 3), 0)
                non_seat = [t for t in tiles if 3 < t <= 36]
                discard = non_seat[-1] if non_seat else -1
                self.tracker.on_discard(seat, discard)
            elif 'NotifyLiqi' in name:
                log_info("[MOD] Liqi declared")
            elif 'NotifyHu' in name:
                log_info("[MOD] Hu! Round ended")
                self.tracker.in_game = False
        except Exception as e:
            log_info(f"[MOD] Error: {e}")

    def websocket_end(self, flow):
        log_info("[MOD] WebSocket disconnected")


addons = [MajsoulAddon]
