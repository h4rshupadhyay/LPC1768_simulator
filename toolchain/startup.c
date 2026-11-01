/* SPDX-License-Identifier: MIT */
#include "LPC17xx.h"
extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
extern int main(void);
void Reset_Handler(void);
void Default_Handler(void) { for (;;) {} }
#define HANDLER(name) void name(void) __attribute__((weak, alias("Default_Handler")))
HANDLER(NMI_Handler); HANDLER(HardFault_Handler); HANDLER(MemManage_Handler);
HANDLER(BusFault_Handler); HANDLER(UsageFault_Handler); HANDLER(SVC_Handler);
HANDLER(DebugMon_Handler); HANDLER(PendSV_Handler); HANDLER(SysTick_Handler);
HANDLER(WDT_IRQHandler); HANDLER(TIMER0_IRQHandler); HANDLER(TIMER1_IRQHandler);
HANDLER(TIMER2_IRQHandler); HANDLER(TIMER3_IRQHandler); HANDLER(UART0_IRQHandler);
HANDLER(UART1_IRQHandler); HANDLER(UART2_IRQHandler); HANDLER(UART3_IRQHandler);
HANDLER(PWM1_IRQHandler); HANDLER(I2C0_IRQHandler); HANDLER(I2C1_IRQHandler);
HANDLER(I2C2_IRQHandler); HANDLER(SPI_IRQHandler); HANDLER(SSP0_IRQHandler);
HANDLER(SSP1_IRQHandler); HANDLER(PLL0_IRQHandler); HANDLER(RTC_IRQHandler);
HANDLER(EINT0_IRQHandler); HANDLER(EINT1_IRQHandler); HANDLER(EINT2_IRQHandler);
HANDLER(EINT3_IRQHandler); HANDLER(ADC_IRQHandler); HANDLER(BOD_IRQHandler);
HANDLER(USB_IRQHandler); HANDLER(CAN_IRQHandler); HANDLER(DMA_IRQHandler);
HANDLER(I2S_IRQHandler); HANDLER(ENET_IRQHandler); HANDLER(RIT_IRQHandler);
HANDLER(MCPWM_IRQHandler); HANDLER(QEI_IRQHandler); HANDLER(PLL1_IRQHandler);
HANDLER(USBActivity_IRQHandler); HANDLER(CANActivity_IRQHandler);

__attribute__((section(".vectors"),used))
const uintptr_t vector_table[] = {
  (uintptr_t)&_estack, (uintptr_t)Reset_Handler, (uintptr_t)NMI_Handler,
  (uintptr_t)HardFault_Handler, (uintptr_t)MemManage_Handler,
  (uintptr_t)BusFault_Handler, (uintptr_t)UsageFault_Handler, 0, 0, 0, 0,
  (uintptr_t)SVC_Handler, (uintptr_t)DebugMon_Handler, 0,
  (uintptr_t)PendSV_Handler, (uintptr_t)SysTick_Handler,
  (uintptr_t)WDT_IRQHandler, (uintptr_t)TIMER0_IRQHandler,
  (uintptr_t)TIMER1_IRQHandler, (uintptr_t)TIMER2_IRQHandler,
  (uintptr_t)TIMER3_IRQHandler, (uintptr_t)UART0_IRQHandler,
  (uintptr_t)UART1_IRQHandler, (uintptr_t)UART2_IRQHandler,
  (uintptr_t)UART3_IRQHandler, (uintptr_t)PWM1_IRQHandler,
  (uintptr_t)I2C0_IRQHandler, (uintptr_t)I2C1_IRQHandler,
  (uintptr_t)I2C2_IRQHandler, (uintptr_t)SPI_IRQHandler,
  (uintptr_t)SSP0_IRQHandler, (uintptr_t)SSP1_IRQHandler,
  (uintptr_t)PLL0_IRQHandler, (uintptr_t)RTC_IRQHandler,
  (uintptr_t)EINT0_IRQHandler, (uintptr_t)EINT1_IRQHandler,
  (uintptr_t)EINT2_IRQHandler, (uintptr_t)EINT3_IRQHandler,
  (uintptr_t)ADC_IRQHandler, (uintptr_t)BOD_IRQHandler,
  (uintptr_t)USB_IRQHandler, (uintptr_t)CAN_IRQHandler,
  (uintptr_t)DMA_IRQHandler, (uintptr_t)I2S_IRQHandler,
  (uintptr_t)ENET_IRQHandler, (uintptr_t)RIT_IRQHandler,
  (uintptr_t)MCPWM_IRQHandler, (uintptr_t)QEI_IRQHandler,
  (uintptr_t)PLL1_IRQHandler, (uintptr_t)USBActivity_IRQHandler,
  (uintptr_t)CANActivity_IRQHandler
};
void Reset_Handler(void) {
  uint32_t *src = &_sidata;
  for (uint32_t *dst = &_sdata; dst < &_edata;) *dst++ = *src++;
  for (uint32_t *dst = &_sbss; dst < &_ebss;) *dst++ = 0;
  SystemInit();
  (void)main();
  for (;;) {}
}
