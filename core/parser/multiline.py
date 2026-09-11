import re
from typing import List

# Very small heuristic-based coalescer for stack traces and indented continuations.
# Input: list of raw lines (strings). Output: list of grouped raw-line lists.

STACK_TRACE_CONT = re.compile(r"^\s+at\s+|^\s+File \"|^\s+\.")
INDENTED = re.compile(r"^\s+")


def coalesce(lines: List[str], max_group_lines: int = 200):
    groups = []
    if not lines:
        return groups
    cur = [lines[0]]
    for line in lines[1:]:
        # continuation if indented or matches stack trace continuation pattern
        if STACK_TRACE_CONT.match(line) or INDENTED.match(line):
            cur.append(line)
        else:
            # if next line looks like a continuation but previous was very short,
            # be conservative and only attach if it looks like a stack trace
            groups.append(cur)
            cur = [line]
        if len(cur) >= max_group_lines:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups
