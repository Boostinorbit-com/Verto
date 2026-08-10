#pragma once
// An unrelated TU — no dependency on stats.cpp. Its test must NOT be selected when BOOSTOPT
// targets stats.cpp (that's what 2A-1 TU-targeting proves).
int unrelated(int x);
