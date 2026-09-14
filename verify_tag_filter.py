import json

# Mock objects to simulate the logic in tasks.py
class MockSample:
    def __init__(self, name, tags):
        self.name = name
        self.tags = tags

class MockLeaderboardMetric:
    def __init__(self, tag_filter):
        self.tag_filter = tag_filter

def test_filtering_logic(tag_filter, sample_list):
    lm = MockLeaderboardMetric(tag_filter)
    dataset_samples = sample_list
    
    # Replicate logic from tasks.py
    current_metric_samples = dataset_samples
    if lm.tag_filter:
        tags = [t.strip().lower() for t in lm.tag_filter.split(',')]
        include_tags = [t for t in tags if not t.startswith('!')]
        exclude_tags = [t[1:] for t in tags if t.startswith('!')]
        
        filtered_indices = []
        for i, sample in enumerate(dataset_samples):
            sample_tags = [t.strip().lower() for t in (sample.tags.split(',') if sample.tags else [])]
            
            # Check excludes
            if any(t in sample_tags for t in exclude_tags):
                continue
            
            # Check includes
            if not include_tags or any(t in sample_tags for t in include_tags):
                filtered_indices.append(i)
        
        current_metric_samples = [dataset_samples[i] for i in filtered_indices]
    
    return [s.name for s in current_metric_samples]

# Test cases
samples = [
    MockSample("s1", "valid,subsetA"),
    MockSample("s2", "valid,subsetB"),
    MockSample("s3", "noise,subsetA"),
    MockSample("s4", "noise,subsetB"),
]

test_cases = [
    {"filter": "valid", "expected": ["s1", "s2"]},
    {"filter": "noise", "expected": ["s3", "s4"]},
    {"filter": "subsetA", "expected": ["s1", "s3"]},
    {"filter": "!noise", "expected": ["s1", "s2"]},
    {"filter": "valid,!subsetB", "expected": ["s1"]},
    {"filter": "subsetA,subsetB", "expected": ["s1", "s2", "s3", "s4"]},
    {"filter": "", "expected": ["s1", "s2", "s3", "s4"]},
    {"filter": None, "expected": ["s1", "s2", "s3", "s4"]},
]

for tc in test_cases:
    result = test_filtering_logic(tc["filter"], samples)
    if result == tc["expected"]:
        print(f"PASS: filter='{tc['filter']}' -> {result}")
    else:
        print(f"FAIL: filter='{tc['filter']}' -> expected {tc['expected']}, got {result}")
