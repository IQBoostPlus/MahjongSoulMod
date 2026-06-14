"""
雀魂 MITM 代理插件 - mitmdump -s addon.py

工作原理:
  1. mitmproxy 拦截雀魂的 WebSocket 流量
  2. 解码 liqi protobuf 消息 → 重建牌局状态
  3. AI 引擎决策 → 写入动作队列
  4. 启动器读取队列并模拟鼠标点击
"""

import json, os, struct, time
from pathlib import Path


# ── 配置 ──
HOME = str(Path.home())
BASE = os.path.join(HOME, ".majsoul_automod")
ACTION_QUEUE = os.path.join(BASE, "action_queue.json")
EVENT_LOG = os.path.join(BASE, "events.log")
LOG_FILE = os.path.join(BASE, "logs", "addon.log")
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)


def log_info(msg):
    """安全日志(兼容有无 mitmproxy ctx)"""
    try: from mitmproxy import ctx; ctx.log.info(msg)
    except: pass
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except: pass


# ═══════════════════════════════════════════════
# 1. 牌编码工具
# ═══════════════════════════════════════════════

SUIT_NAMES = {0: "m", 1: "p", 2: "s", 3: "z"}

def tile_str(t):
    if t < 0 or t > 36: return "?"
    s = (t // 9) if t < 34 else ((t - 34) // 9)
    v = (t % 9 + 1) if t < 34 else ((t - 34) % 9 + 1)
    return f"{v}{SUIT_NAMES.get(s, '?')}{'r' if t >= 34 else ''}"

def hand_str(tiles): return ",".join(tile_str(t) for t in tiles)

SUITS_MAN = range(0, 9)
SUITS_PIN = range(9, 18)
SUITS_SOU = range(18, 27)
YAOCHU = {0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33}


# ═══════════════════════════════════════════════
# 2. 协议解码器
# ═══════════════════════════════════════════════

def _varint(data, pos):
    value = 0; shift = 0
    while pos < len(data):
        b = data[pos]
        value |= (b & 0x7f) << shift
        shift += 7; pos += 1
        if (b & 0x80) == 0: break
    return value, pos

def decode_wrapper(data):
    """解码 Wrapper: 2字节长度 + protobuf {name, data}"""
    if len(data) < 2: return None
    msg_len = struct.unpack('<H', data[:2])[0]
    if msg_len <= 0 or msg_len + 2 > len(data): return None

    pos = 2; result = {"name": "", "data": b""}
    end = pos + msg_len
    while pos < end:
        if pos >= len(data): break
        tag = data[pos]; pos += 1
        wire = tag & 0x07; field = tag >> 3

        if field == 1 and wire == 2:  # name (string)
            l, pos = _varint(data, pos)
            result["name"] = data[pos:pos+l].decode('utf-8', errors='replace')
            pos += l
        elif field == 2 and wire == 2:  # data (bytes)
            l, pos = _varint(data, pos)
            result["data"] = data[pos:pos+l]
            pos += l
        elif wire == 0:  # varint skip
            _, pos = _varint(data, pos)
        elif wire == 2:  # len-delimited skip
            l, pos = _varint(data, pos); pos += l
        elif wire == 5:  # 32-bit skip
            pos += 4
        else:
            pos += 1
    return result

def extract_varints(data):
    """从 bytes 中提取所有 varint 值 (0-255)"""
    vals = []
    pos = 0
    while pos < len(data):
        b = data[pos]
        if b & 0x80:  # not a field tag (tag < 128)
            pos += 1; continue
        # b is a field tag
        wire = b & 0x07
        pos += 1
        if wire == 0:  # varint
            v, pos = _varint(data, pos)
            if v < 256: vals.append(v)
        elif wire == 2:  # skip len-delimited
            l, pos = _varint(data, pos); pos += l
        elif wire == 5:  # 32-bit
            pos += 4
        else:
            pos += 1
    return vals


# ═══════════════════════════════════════════════
# 3. 牌局追踪器 + AI
# ═══════════════════════════════════════════════

class GameTracker:
    """对局状态追踪 + AI 决策"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.in_game = False
        self.seat = 0; self.hand = []
        self.scores = [25000]*4
        self.deposits = [0]*4
        self.round_wind = 0; self.round_num = 0
        self.honba = 0; self.dealer = 0
        self.left_tiles = 70; self.dora = -1
        self.last_action = ""
        self.seen = [0]*37
        self.players = [{'discards':[], 'melds':[], 'liqi':False, 'score':25000}
                        for _ in range(4)]

    def add_seen(self, t):
        if 0 <= t < 37: self.seen[t] += 1

    def on_new_round(self, data):
        self.reset()
        self.in_game = True
        vals = extract_varints(data)
        # 手牌是 0-36 的值, 取前13-14个
        tiles = [v for v in vals if 0 <= v <= 36]
        if len(tiles) >= 13:
            self.hand = tiles[:14]
            for t in self.hand: self.add_seen(t)
        log_info(f"NEW ROUND: seat={self.seat} hand({len(self.hand)}) dora={self.dora}")

    def on_draw(self, data):
        vals = extract_varints(data)
        tiles = [v for v in vals if 0 <= v <= 36]
        if tiles:
            tile = tiles[-1]
            self.hand.append(tile)
            self.add_seen(tile)
            log_info(f"DRAW: {tile_str(tile)} → {len(self.hand)} tiles")

    def on_discard(self, data):
        vals = extract_varints(data)
        tiles = [v for v in vals if 0 <= v <= 36]
        tiles.sort()
        if not tiles: return

        # 简化: 最后一个 < 4 的是座位
        seats = [v for v in tiles if 0 <= v <= 3]
        seat = seats[-1] if seats else 0

        # 牌是剩余中最大或最小的
        discards_pool = [v for v in tiles if 10 <= v <= 36]
        if discards_pool:
            tile = discards_pool[-1]
        else:
            tile = tiles[-1]

        if 0 <= tile <= 36:
            self.players[seat]['discards'].append(tile)
            self.add_seen(tile)
            if seat == self.seat and tile in self.hand:
                self.hand.remove(tile)
                self._trigger_ai()

    def _trigger_ai(self):
        if not self.hand: return
        decision = self._decide()
        try:
            with open(ACTION_QUEUE, 'w') as f:
                json.dump(decision, f)
        except: pass

    def _decide(self):
        """AI 决策: 向听数最少 + 安全度最高"""
        if not self.hand: return {"action": "pass"}
        hand = self.hand[:]
        best_score = -999; best = hand[0]

        for tile in sorted(set(hand)):
            new_hand = hand.copy()
            new_hand.remove(tile)
            shanten = self._calc_shanten(new_hand)
            remaining = 4 - (self.seen[tile] if 0 <= tile < 37 else 0)
            score = -shanten * 10 + remaining
            if score > best_score:
                best_score = score; best = tile

        # 找手牌中的位置索引
        hand_positions = [i for i, t in enumerate(hand) if t == best]
        pos = hand_positions[0] if hand_positions else 0

        return {
            "action": "discard",
            "tile_id": best,
            "tile_str": tile_str(best),
            "hand_pos": pos,        # 手牌中的位置
            "hand_count": len(hand),
            "full_hand": hand_str(hand),
            "timestamp": time.time()
        }

    def _calc_shanten(self, hand):
        """向听数计算"""
        counts = [0]*34
        for t in hand:
            if 0 <= t < 34: counts[t] += 1

        def normal_shanten(counts, total):
            needed = total // 3; best = 999
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
            best = 999; c = counts[pos]

            if pos < 27 and pos%9<7 and counts[pos]>0 and counts[pos+1]>0 and counts[pos+2]>0:
                counts[pos]-=1; counts[pos+1]-=1; counts[pos+2]-=1
                s = _calc_mentsu(counts, target, melds+1, partials)
                counts[pos]+=1; counts[pos+1]+=1; counts[pos+2]+=1
                if s < best: best = s
            if c >= 3:
                counts[pos]-=3; s = _calc_mentsu(counts, target, melds+1, partials)
                counts[pos]+=3; if s < best: best = s
            if c >= 2:
                counts[pos]-=2; s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=2; if s < best: best = s
            if pos < 27 and pos%9<8 and counts[pos]>0 and counts[pos+1]>0:
                counts[pos]-=1; counts[pos+1]-=1
                s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=1; counts[pos+1]+=1; if s < best: best = s
            if pos < 27 and pos%9<7 and counts[pos]>0 and counts[pos+2]>0:
                counts[pos]-=1; counts[pos+2]-=1
                s = _calc_mentsu(counts, target, melds, partials+1)
                counts[pos]+=1; counts[pos+2]+=1; if s < best: best = s

            counts[pos] = 0
            s = _calc_mentsu(counts, target, melds, partials)
            counts[pos] = c
            if s < best: best = s
            return best

        total = len(hand)
        return normal_shanten(counts, total)


# ═══════════════════════════════════════════════
# 4. mitmproxy 插件入口
# ═══════════════════════════════════════════════

class MajsoulAddon:
    def __init__(self):
        self.tracker = GameTracker()
        log_info("[MOD] Addon loaded")

    def websocket_message(self, flow):
        if not flow.messages: return
        msg = flow.messages[-1]
        if msg.from_client: return  # 只处理服务器→客户端

        data = msg.content
        if not data or len(data) < 4: return

        try:
            wrapper = decode_wrapper(data)
            if not wrapper or 'name' not in wrapper: return
            name = wrapper['name']
            payload = wrapper.get('data', b'')

            if 'NotifyNewRound' in name:
                self.tracker.on_new_round(payload)
            elif 'NotifyDrawTile' in name or 'NotifyDealTile' in name:
                self.tracker.on_draw(payload)
            elif 'NotifyDiscardTile' in name:
                self.tracker.on_discard(payload)
            elif 'NotifyHu' in name:
                log_info("[MOD] Round ended")
                self.tracker.in_game = False
        except Exception as e:
            log_info(f"[MOD] parse error: {e}")

    def websocket_end(self, flow):
        log_info("[MOD] WebSocket closed")


addons = [MajsoulAddon]
