/* SPDX-License-Identifier: MIT
 * LPC1768 register subset used by this lab. Independently defined from NXP
 * UM10360 register offsets. This is not a full vendor SDK or chip model.
 */
#ifndef LPC_LAB_LPC17XX_H
#define LPC_LAB_LPC17XX_H
#include <stdint.h>
#include <stddef.h>
#define __I volatile const
#define __O volatile
#define __IO volatile
#define __irq
#define __packed __attribute__((__packed__))
#define __weak __attribute__((weak))
#define __NOP() __asm__ volatile("nop")
#define __WFI() __asm__ volatile("wfi")
#define __enable_irq() __asm__ volatile("cpsie i" ::: "memory")
#define __disable_irq() __asm__ volatile("cpsid i" ::: "memory")
#define __NVIC_PRIO_BITS 5u

typedef struct {
  __IO uint32_t CTRL;
  __IO uint32_t LOAD;
  __IO uint32_t VAL;
  __I uint32_t CALIB;
} SysTick_Type;
#define SysTick ((SysTick_Type *)0xE000E010u)
#define SysTick_CTRL_ENABLE_Pos 0u
#define SysTick_CTRL_ENABLE_Msk (1u << SysTick_CTRL_ENABLE_Pos)
#define SysTick_CTRL_TICKINT_Pos 1u
#define SysTick_CTRL_TICKINT_Msk (1u << SysTick_CTRL_TICKINT_Pos)
#define SysTick_CTRL_CLKSOURCE_Pos 2u
#define SysTick_CTRL_CLKSOURCE_Msk (1u << SysTick_CTRL_CLKSOURCE_Pos)
#define SysTick_CTRL_COUNTFLAG_Pos 16u
#define SysTick_CTRL_COUNTFLAG_Msk (1u << SysTick_CTRL_COUNTFLAG_Pos)
#define SysTick_LOAD_RELOAD_Msk 0x00FFFFFFu
#define SysTick_VAL_CURRENT_Msk 0x00FFFFFFu

typedef enum {
  NonMaskableInt_IRQn=-14, HardFault_IRQn=-13, MemoryManagement_IRQn=-12,
  BusFault_IRQn=-11, UsageFault_IRQn=-10, SVCall_IRQn=-5,
  DebugMonitor_IRQn=-4, PendSV_IRQn=-2, SysTick_IRQn=-1,
  WDT_IRQn=0, TIMER0_IRQn=1, TIMER1_IRQn=2, TIMER2_IRQn=3, TIMER3_IRQn=4,
  UART0_IRQn=5, UART1_IRQn=6, UART2_IRQn=7, UART3_IRQn=8, PWM1_IRQn=9,
  I2C0_IRQn=10, I2C1_IRQn=11, I2C2_IRQn=12, SPI_IRQn=13,
  SSP0_IRQn=14, SSP1_IRQn=15, PLL0_IRQn=16, RTC_IRQn=17,
  EINT0_IRQn=18, EINT1_IRQn=19, EINT2_IRQn=20, EINT3_IRQn=21,
  ADC_IRQn=22, BOD_IRQn=23, USB_IRQn=24, CAN_IRQn=25, DMA_IRQn=26,
  I2S_IRQn=27, ENET_IRQn=28, RIT_IRQn=29, MCPWM_IRQn=30, QEI_IRQn=31,
  PLL1_IRQn=32, USBActivity_IRQn=33, CANActivity_IRQn=34
} IRQn_Type;

static inline void NVIC_EnableIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) ((volatile uint32_t *)0xE000E100)[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_DisableIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) ((volatile uint32_t *)0xE000E180)[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_ClearPendingIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) ((volatile uint32_t *)0xE000E280)[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_SetPendingIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) ((volatile uint32_t *)0xE000E200)[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline uint32_t NVIC_GetPendingIRQ(IRQn_Type irq) {
  return ((volatile uint32_t *)0xE000E200)[(unsigned)irq/32] >> ((unsigned)irq%32) & 1u;
}
static inline void NVIC_SetPriority(IRQn_Type irq, uint32_t priority) {
  if ((int)irq >= 0) ((volatile uint8_t *)0xE000E400)[(unsigned)irq] = (uint8_t)(priority << 3);
}
static inline uint32_t SysTick_Config(uint32_t ticks) {
  if (ticks == 0 || ticks > 0x01000000u) return 1;
  SysTick->LOAD = ticks - 1u;
  NVIC_SetPriority(SysTick_IRQn, (1u << __NVIC_PRIO_BITS) - 1u);
  SysTick->VAL = 0;
  SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_TICKINT_Msk | SysTick_CTRL_ENABLE_Msk;
  return 0;
}

typedef struct {
  __IO uint32_t FIODIR; uint32_t RESERVED0[3];
  __IO uint32_t FIOMASK, FIOPIN, FIOSET, FIOCLR;
} LPC_GPIO_TypeDef;
typedef struct {
  __IO uint32_t PINSEL0, PINSEL1, PINSEL2, PINSEL3, PINSEL4, PINSEL5;
  __IO uint32_t PINSEL6, PINSEL7, PINSEL8, PINSEL9, PINSEL10;
  uint32_t RESERVED0[5];
  __IO uint32_t PINMODE0, PINMODE1, PINMODE2, PINMODE3, PINMODE4;
  __IO uint32_t PINMODE5, PINMODE6, PINMODE7, PINMODE8, PINMODE9;
  __IO uint32_t PINMODE_OD0, PINMODE_OD1, PINMODE_OD2, PINMODE_OD3, PINMODE_OD4;
  __IO uint32_t I2CPADCFG;
} LPC_PINCON_TypeDef;
typedef struct {
  __IO uint32_t FLASHCFG; uint32_t RESERVED0[31];
  __IO uint32_t PLL0CON, PLL0CFG, PLL0STAT, PLL0FEED; uint32_t RESERVED1[4];
  __IO uint32_t PLL1CON, PLL1CFG, PLL1STAT, PLL1FEED; uint32_t RESERVED2[4];
  __IO uint32_t PCON, PCONP; uint32_t RESERVED3[15];
  __IO uint32_t CCLKCFG, USBCLKCFG, CLKSRCSEL, CANSLEEPCLR, CANWAKEFLAGS;
  uint32_t RESERVED4[10];
  __IO uint32_t EXTINT; uint32_t RESERVED5;
  __IO uint32_t EXTMODE, EXTPOLAR; uint32_t RESERVED6[12];
  __IO uint32_t RSID; uint32_t RESERVED7[7];
  __IO uint32_t SCS, IRCTRIM, PCLKSEL0, PCLKSEL1; uint32_t RESERVED8[4];
  __IO uint32_t USBIntSt, DMAREQSEL, CLKOUTCFG;
} LPC_SC_TypeDef;
typedef struct {
  __IO uint32_t IR, TCR, TC, PR, PC, MCR, MR0, MR1, MR2, MR3, CCR;
  __IO uint32_t CR0, CR1; uint32_t RESERVED0[2]; __IO uint32_t EMR;
  uint32_t RESERVED1[12]; __IO uint32_t CTCR;
} LPC_TIM_TypeDef;
typedef struct {
  __IO uint32_t IR, TCR, TC, PR, PC, MCR, MR0, MR1, MR2, MR3, CCR;
  __IO uint32_t CR0, CR1, CR2, CR3; uint32_t RESERVED0;
  __IO uint32_t MR4, MR5, MR6, PCR, LER; uint32_t RESERVED1[7];
  __IO uint32_t CTCR;
} LPC_PWM_TypeDef;
typedef struct {
  __IO uint32_t ADCR, ADGDR; uint32_t RESERVED0; __IO uint32_t ADINTEN;
  __IO uint32_t ADDR0, ADDR1, ADDR2, ADDR3, ADDR4, ADDR5, ADDR6, ADDR7;
  __IO uint32_t ADSTAT, ADTRM;
} LPC_ADC_TypeDef;

#define LPC_GPIO0 ((LPC_GPIO_TypeDef *)0x2009C000u)
#define LPC_GPIO1 ((LPC_GPIO_TypeDef *)0x2009C020u)
#define LPC_GPIO2 ((LPC_GPIO_TypeDef *)0x2009C040u)
#define LPC_GPIO3 ((LPC_GPIO_TypeDef *)0x2009C060u)
#define LPC_GPIO4 ((LPC_GPIO_TypeDef *)0x2009C080u)
#define LPC_PINCON ((LPC_PINCON_TypeDef *)0x4002C000u)
#define LPC_SC ((LPC_SC_TypeDef *)0x400FC000u)
#define LPC_ADC ((LPC_ADC_TypeDef *)0x40034000u)
#define LPC_PWM1 ((LPC_PWM_TypeDef *)0x40018000u)
#define LPC_TIM0 ((LPC_TIM_TypeDef *)0x40004000u)
#define LPC_TIM1 ((LPC_TIM_TypeDef *)0x40008000u)
#define LPC_TIM2 ((LPC_TIM_TypeDef *)0x40090000u)
#define LPC_TIM3 ((LPC_TIM_TypeDef *)0x40094000u)

extern uint32_t SystemCoreClock;
void SystemInit(void);
void SystemCoreClockUpdate(void);
#endif
