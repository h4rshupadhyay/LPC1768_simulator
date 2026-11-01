/* SPDX-License-Identifier: MIT */
#include "LPC17xx.h"
uint32_t SystemCoreClock = 100000000u;

/* Same default clock frequency as the original Keil/CMSIS lab startup.
 * This configures the simulator's documented clock subset. Real hardware
 * requires the oscillator/PLL lock/feed sequencing from a complete SDK.
 */
void SystemInit(void) {
  LPC_SC->SCS = 0x20;
  LPC_SC->CLKSRCSEL = 1;
  LPC_SC->CCLKCFG = 3;
  LPC_SC->PLL0CFG = 0x00050063;
  LPC_SC->PLL0CON = 3;
  LPC_SC->PCLKSEL0 = 0;
  LPC_SC->PCLKSEL1 = 0;
  SystemCoreClockUpdate();
}
void SystemCoreClockUpdate(void) {
  unsigned source = LPC_SC->CLKSRCSEL & 3u;
  uint32_t hz = source == 1 ? 12000000u : source == 2 ? 32768u : 4000000u;
  uint32_t divisor = (LPC_SC->CCLKCFG & 255u) + 1u;
  if ((LPC_SC->PLL0CON & 3u) == 3u) {
    uint32_t cfg = LPC_SC->PLL0CFG;
    uint64_t numerator = (uint64_t)hz * 2u * ((cfg & 32767u) + 1u);
    SystemCoreClock = (uint32_t)(numerator / ((((cfg >> 16) & 255u) + 1u) * divisor));
    return;
  }
  SystemCoreClock = hz / divisor;
}
