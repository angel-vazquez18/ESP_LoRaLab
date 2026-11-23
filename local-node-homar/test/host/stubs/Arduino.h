#pragma once
#include <stddef.h>
#include <stdint.h>
enum gpio_num_t { GPIO_NUM_4 = 4, GPIO_NUM_6 = 6, GPIO_NUM_14 = 14, GPIO_NUM_16 = 16,
                 GPIO_NUM_17 = 17, GPIO_NUM_25 = 25, GPIO_NUM_26 = 26,
                 GPIO_NUM_27 = 27, GPIO_NUM_33 = 33, GPIO_NUM_38 = 38,
                 GPIO_NUM_39 = 39, GPIO_NUM_40 = 40, GPIO_NUM_41 = 41,
                 GPIO_NUM_47 = 47, GPIO_NUM_48 = 48 };
struct FakeSerial {
  template <typename... Args> void printf(const char*, Args...) {}
  void println(const char* = "") {}
  void print(const char*) {}
};
extern FakeSerial Serial;
void delay(uint32_t ms);
void delayMicroseconds(uint32_t us);
