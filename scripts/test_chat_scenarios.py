# -*- coding: utf-8 -*-
"""
多輪對話語意測試腳本

測試重點：
1. 短回覆（有/沒有/對）能否正確填 slot
2. 口語化說法能否被正確理解
3. 風險等級是否跟著對話內容更新

用法：
  python scripts/test_chat_scenarios.py
  python scripts/test_chat_scenarios.py --url http://localhost:8000
  python scripts/test_chat_scenarios.py --scenario violence  # 只跑特定場景
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from typing import List, Optional


# ======================
# 顏色輸出
# ======================

def green(s): return f"\033[92m{s}\033[0m"
def red(s): return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def cyan(s): return f"\033[96m{s}\033[0m"
def bold(s): return f"\033[1m{s}\033[0m"


# ======================
# API 呼叫
# ======================

def call_chat(url: str, messages: list, session_id: str = "test") -> dict:
    payload = json.dumps({
        "messages": messages,
        "session_id": session_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(red(f"  HTTP {e.code}: {body[:200]}"))
        return {}
    except Exception as e:
        print(red(f"  Error: {e}"))
        return {}


# ======================
# 輸出工具
# ======================

def print_turn(turn_num: int, user_msg: str, resp: dict):
    extracted = resp.get("extracted", {})
    risk = resp.get("risk_level", "?")
    score = resp.get("risk_score", 0)
    reply = resp.get("reply", "")

    risk_color = green if risk == "Low" else yellow if risk == "Medium" else red
    print(f"\n  {bold(f'Turn {turn_num}')} — 使用者：{cyan(user_msg)}")
    print(f"  助理：{reply[:100]}{'…' if len(reply) > 100 else ''}")
    print(f"  風險：{risk_color(risk)} ({score:.2f})  |  "
          f"類別：{extracted.get('category','?')}  |  "
          f"受傷：{extracted.get('people_injured','?')}  |  "
          f"武器：{extracted.get('weapon','?')}  |  "
          f"危險持續：{extracted.get('danger_active','?')}  |  "
          f"意識：{extracted.get('conscious','?')}  |  "
          f"呼吸困難：{extracted.get('breathing_difficulty','?')}")


def check(label: str, actual, expected, *, warn_only: bool = False):
    if actual == expected:
        print(f"  {green('OK')} {label}: {actual}")
        return True
    else:
        marker = yellow("?!") if warn_only else red("NG")
        print(f"  {marker} {label}: got {actual!r}, expected {expected!r}")
        return warn_only  # warn_only=True → warning only; warn_only=False → real failure


# ======================
# 測試場景定義
# ======================

def run_scenario(name: str, url: str, turns: list, checks_per_turn: list):
    """
    turns: list of user messages (strings)
    checks_per_turn: list of dicts { turn_index: {field: expected_value} }
    """
    print(f"\n{'─'*60}")
    print(bold(f"場景：{name}"))
    print('─'*60)

    messages = []
    passed = True
    final_resp = {}

    for i, user_msg in enumerate(turns):
        messages.append({"role": "user", "content": user_msg})
        resp = call_chat(url, messages, session_id=f"test_{name}_{i}")
        if not resp:
            print(red("  無回應，跳過後續 turns"))
            passed = False
            break

        assistant_reply = resp.get("reply", "")
        messages.append({"role": "assistant", "content": assistant_reply})
        final_resp = resp

        print_turn(i + 1, user_msg, resp)

        # 執行這一輪的檢查
        if i < len(checks_per_turn) and checks_per_turn[i]:
            for field, expected in checks_per_turn[i].items():
                if field == "risk_level":
                    ok = check(f"  risk_level", resp.get("risk_level"), expected)
                elif field == "risk_score_gte":
                    actual = resp.get("risk_score", 0)
                    ok = actual >= expected
                    marker = green("✓") if ok else red("✗")
                    print(f"  {marker}  risk_score >= {expected}: {actual:.2f}")
                else:
                    extracted = resp.get("extracted", {})
                    ok = check(f"  {field}", extracted.get(field), expected)
                if not ok:
                    passed = False

    status = green("PASS") if passed else red("FAIL")
    print(f"\n  {bold('結果')}: {status}")
    return passed


# ======================
# 具體測試場景
# ======================

SCENARIOS = {}


def scenario(name):
    def decorator(fn):
        SCENARIOS[name] = fn
        return fn
    return decorator


@scenario("violence_short_yes")
def _(url):
    """暴力事件：追問後用戶回「有」能否正確填 weapon=True"""
    return run_scenario(
        name="暴力事件 — 追問武器 → 用戶說「有」",
        url=url,
        turns=[
            "樓下有人打架，很大聲",
            "有",          # 回答「有沒有人拿武器」
            "有流血",      # 加一個傷亡確認
        ],
        checks_per_turn=[
            {
                "category": "暴力事件",
            },
            {
                "weapon": True,   # 「有」應該填 weapon=True
            },
            {
                "people_injured": True,
            },
        ],
    )


@scenario("violence_short_no")
def _(url):
    """暴力事件：追問後用戶回「沒有」"""
    return run_scenario(
        name="暴力事件 — 追問武器 → 用戶說「沒有」",
        url=url,
        turns=[
            "有人在公園打架",
            "沒有",        # 沒有武器
            "沒有人受傷",  # 沒有受傷
        ],
        checks_per_turn=[
            {"category": "暴力事件"},
            {"weapon": False},
            {"people_injured": False},
        ],
    )


@scenario("medical_unconscious")
def _(url):
    """醫療急症：叫不醒 → 應立即升級風險"""
    return run_scenario(
        name="醫療急症 — 叫不醒 + 無呼吸",
        url=url,
        turns=[
            "有人暈倒在地鐵站",
            "叫不醒",          # 意識喪失
            "沒有呼吸",        # 無呼吸
        ],
        checks_per_turn=[
            {"category": "醫療急症"},
            {"conscious": False, "risk_level": "High"},
            {"breathing_difficulty": True, "risk_level": "High"},
        ],
    )


@scenario("medical_short_answers")
def _(url):
    """醫療急症：全程用短回覆回答"""
    return run_scenario(
        name="醫療急症 — 全短回覆（有/沒有）",
        url=url,
        turns=[
            "我媽媽突然昏倒了",
            "有",     # 有反應（意識OK）
            "沒有",   # 沒有呼吸困難
        ],
        checks_per_turn=[
            {"category": "醫療急症"},
            {"conscious": True},
            {"breathing_difficulty": False},
        ],
    )


@scenario("fire_active")
def _(url):
    """火災：確認火勢持續"""
    return run_scenario(
        name="火災 — 火勢持續 + 有人受困",
        url=url,
        turns=[
            "對面大樓冒出濃煙",
            "還在燒，越來越大",   # danger_active=True
            "有，3樓有人喊救命",  # people_injured=True
        ],
        checks_per_turn=[
            {"category": "火災"},
            {"danger_active": True, "risk_level": "High"},
            {"people_injured": True},
        ],
    )


@scenario("fire_short_no")
def _(url):
    """火災：短回覆說沒事"""
    return run_scenario(
        name="火災 — 追問火勢 → 回「沒有了」",
        url=url,
        turns=[
            "聞到焦味",
            "沒有了",    # 沒有火，危險解除
            "沒有",      # 沒有人受困
        ],
        checks_per_turn=[
            {},
            {"danger_active": False},
            {"people_injured": False},
        ],
    )


@scenario("traffic_injury")
def _(url):
    """交通事故：有人受傷"""
    return run_scenario(
        name="交通事故 — 機車追撞 + 有人受傷",
        url=url,
        turns=[
            "路口剛發生車禍，機車追撞",
            "有，騎士倒在地上流血",
            "還在路中間，沒有移開",
        ],
        checks_per_turn=[
            {"category": "交通事故"},
            {"people_injured": True, "risk_level": "High"},
            {"danger_active": True},
        ],
    )


@scenario("colloquial_phrasing")
def _(url):
    """口語化說法測試（關鍵字 match 不到的類型）"""
    return run_scenario(
        name="口語化說法 — 不用標準關鍵字",
        url=url,
        turns=[
            "我朋友突然倒下來，整個人不對勁",   # 暗示醫療
            "怎麼叫都沒有反應",                   # conscious=False，沒用「叫不醒」
            "他整個臉色很差，嘴唇有點黑",         # 嚴重症狀
        ],
        checks_per_turn=[
            {"category": "醫療急症"},
            {"conscious": False, "risk_score_gte": 0.7},
            {"risk_score_gte": 0.8},
        ],
    )


@scenario("suspicious_danger_short")
def _(url):
    """可疑人士：確認對方還在"""
    return run_scenario(
        name="可疑人士 — 尾隨 + 短回覆確認持續",
        url=url,
        turns=[
            "有個人一直跟著我",
            "有，還在跟著",     # danger_active=True
        ],
        checks_per_turn=[
            {"category": "可疑人士"},
            {"danger_active": True, "risk_level": "High"},
        ],
    )


# ======================
# 主程式
# ======================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--scenario", default=None, help="只跑指定場景名稱")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    print(bold(f"\nE-CARE 語意對話測試 → {url}"))

    # 確認後端存活
    try:
        urllib.request.urlopen(f"{url}/docs", timeout=5)
    except Exception:
        try:
            urllib.request.urlopen(f"{url}/chat", timeout=5)
        except urllib.error.HTTPError:
            pass  # 405 is fine, server is up
        except Exception as e:
            print(red(f"\n後端無法連線：{e}"))
            print("請先執行 start_backend.ps1")
            sys.exit(1)

    to_run = {}
    if args.scenario:
        if args.scenario not in SCENARIOS:
            print(red(f"找不到場景 '{args.scenario}'，可用：{list(SCENARIOS.keys())}"))
            sys.exit(1)
        to_run = {args.scenario: SCENARIOS[args.scenario]}
    else:
        to_run = SCENARIOS

    results = {}
    for name, fn in to_run.items():
        results[name] = fn(url)

    # 總結
    print(f"\n{'='*60}")
    print(bold("測試總結"))
    print('='*60)
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    for name, ok in results.items():
        marker = green("PASS") if ok else red("FAIL")
        print(f"  [{marker}]  {name}")
    print(f"\n  {bold(f'{passed}/{len(results)}')} 通過")

    if failed:
        print(red(f"\n{failed} 個場景未通過，代表還有語意漏洞需要處理。"))
    else:
        print(green("\n全部通過！"))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
