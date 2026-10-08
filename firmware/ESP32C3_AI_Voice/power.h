#pragma once
#include <stdint.h>
bool powerBegin();
void powerUpdate(bool busy);
void powerNoteActivity();
int powerBatteryMv();
bool powerUsbPresent();
bool powerWokeFromSleep();
