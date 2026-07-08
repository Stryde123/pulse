import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.pattern_detector import detect_patterns, calculate_latency_trend

cases = [
    ("still waiting on the implementation timeline",        ["Repeated Frustration"]),
    ("how do we export our data?",                          ["Data Export Request"]),
    ("we're also looking at alternatives to streamline",    ["Competitor Evaluation Signal"]),
    ("can you send the contract terms and cancellation policy?", ["Contract Term Inquiry"]),
    ("per my last email, we need this ASAP",                ["Repeated Frustration", "Tone Formality Shift"]),
    ("our team has been discussing the roadmap",            ["Internal Discussion Signal"]),
    ("not a priority right now, circle back later",         ["Deprioritization Signal"]),
    ("evaluating other options, please send contract terms",["Contract Term Inquiry", "Competitor Evaluation Signal"]),
    ("this product is amazing, thanks!",                    []),
]

all_pass = True
for text, expected_labels in cases:
    flags = detect_patterns(text)
    got = [f["label"] for f in flags]
    ok = sorted(got) == sorted(expected_labels)
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
        print(f"  [{status}] \"{text[:55]}\"")
        print(f"          expected: {expected_labels}")
        print(f"          got:      {got}")
    else:
        print(f"  [{status}] \"{text[:55]}\"")

# Latency trend test
baseline_msgs = [
    {"is_customer": True,  "timestamp": "1000",  "account_id": 1},
    {"is_customer": False, "timestamp": "4600",  "account_id": 1},  # 1h
    {"is_customer": True,  "timestamp": "10000", "account_id": 1},
    {"is_customer": False, "timestamp": "13600", "account_id": 1},  # 1h
]
recent_msgs = [
    {"is_customer": True,  "timestamp": "20000", "account_id": 1},
    {"is_customer": False, "timestamp": "56000", "account_id": 1},  # 10h  -> ratio ~10x -> penalty 20
]
trend = calculate_latency_trend(recent_msgs, baseline_msgs)
latency_ok = trend["latency_penalty"] == 20
status = "PASS" if latency_ok else "FAIL"
print(f"  [{status}] Latency trend: baseline={trend['baseline_hours']}h recent={trend['recent_hours']}h "
      f"ratio={trend['ratio']} penalty={trend['latency_penalty']}")
if not latency_ok:
    all_pass = False

print()
print("All tests passed!" if all_pass else "SOME TESTS FAILED — see above.")
sys.exit(0 if all_pass else 1)
