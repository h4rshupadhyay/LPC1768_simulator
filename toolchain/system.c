/* SPDX-License-Identifier: MIT */
#include "LPC17xx.h"
uint32_t SystemCoreClock = 100000000u;

static void pll0_feed(void) {
  LPC_SC->PLL0FEED = 0xAA;
  LPC_SC->PLL0FEED = 0x55;
}

/* Same default clock frequency as the original Keil/CMSIS lab startup:
 * 12 MHz crystal, PLL0 M = 100, N = 6 (FCCO = 400 MHz), CCLK = FCCO / 4 = 100 MHz.
 * Follows the UM10360 section 4.5.13 sequence, including the PLL0FEED writes
 * that real hardware requires before PLL0CON/PLL0CFG changes take effect.
 */
void SystemInit(void) {
  LPC_SC->SCS = 0x20;                    /* main oscillator enable */
  while (!(LPC_SC->SCS & 0x40)) {}       /* wait for OSCSTAT */
  LPC_SC->CLKSRCSEL = 1;
  LPC_SC->PLL0CFG = 0x00050063;
  pll0_feed();
  LPC_SC->PLL0CON = 1;                   /* enable */
  pll0_feed();
  LPC_SC->CCLKCFG = 3;
  while (!(LPC_SC->PLL0STAT & (1u << 26))) {}  /* PLOCK0 */
  LPC_SC->PLL0CON = 3;                   /* enable and connect */
  pll0_feed();
  while ((LPC_SC->PLL0STAT & (3u << 24)) != (3u << 24)) {}
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
