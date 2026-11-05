/* SPDX-License-Identifier: MIT
 * LPC1768 register map with CMSIS-compatible type and instance names.
 * Independently defined from NXP UM10360 register offsets and the Arm
 * Cortex-M3 architecture reference. This is not a vendor SDK; peripherals
 * that the simulator does not model still compile but stop at run time.
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
#define __INLINE inline
#define __STATIC_INLINE static inline
#define __ASM __asm__
#define __NOP() __asm__ volatile("nop")
#define __WFI() __asm__ volatile("wfi")
#define __WFE() __asm__ volatile("wfe")
#define __SEV() __asm__ volatile("sev")
#define __DSB() __asm__ volatile("dsb" ::: "memory")
#define __ISB() __asm__ volatile("isb" ::: "memory")
#define __DMB() __asm__ volatile("dmb" ::: "memory")
#define __enable_irq() __asm__ volatile("cpsie i" ::: "memory")
#define __disable_irq() __asm__ volatile("cpsid i" ::: "memory")
#define __NVIC_PRIO_BITS 5u
#define __MPU_PRESENT 1u
#define __Vendor_SysTickConfig 0u

static inline uint32_t __get_PRIMASK(void) {
  uint32_t r; __asm__ volatile("mrs %0, primask" : "=r"(r)); return r;
}
static inline void __set_PRIMASK(uint32_t v) {
  __asm__ volatile("msr primask, %0" :: "r"(v) : "memory");
}

/* ---- Cortex-M3 core peripherals ---------------------------------------- */
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

typedef struct {
  __IO uint32_t ISER[8]; uint32_t RESERVED0[24];
  __IO uint32_t ICER[8]; uint32_t RSERVED1[24];
  __IO uint32_t ISPR[8]; uint32_t RESERVED2[24];
  __IO uint32_t ICPR[8]; uint32_t RESERVED3[24];
  __IO uint32_t IABR[8]; uint32_t RESERVED4[56];
  __IO uint8_t IP[240]; uint32_t RESERVED5[644];
  __O uint32_t STIR;
} NVIC_Type;
typedef struct {
  __I uint32_t CPUID;
  __IO uint32_t ICSR, VTOR, AIRCR, SCR, CCR;
  __IO uint8_t SHP[12];
  __IO uint32_t SHCSR, CFSR, HFSR, DFSR, MMFAR, BFAR, AFSR;
  __I uint32_t PFR[2], DFR, ADR, MMFR[4], ISAR[5];
} SCB_Type;
#define NVIC ((NVIC_Type *)0xE000E100u)
#define SCB ((SCB_Type *)0xE000ED00u)
#define SCB_ICSR_PENDSVSET_Msk (1u << 28)
#define SCB_ICSR_PENDSVCLR_Msk (1u << 27)
#define SCB_ICSR_PENDSTSET_Msk (1u << 26)
#define SCB_ICSR_PENDSTCLR_Msk (1u << 25)
#define SCB_AIRCR_VECTKEY_Pos 16u
#define SCB_AIRCR_PRIGROUP_Pos 8u
#define SCB_AIRCR_PRIGROUP_Msk (7u << SCB_AIRCR_PRIGROUP_Pos)
#define SCB_AIRCR_SYSRESETREQ_Msk (1u << 2)

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
  if ((int)irq >= 0) NVIC->ISER[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_DisableIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) NVIC->ICER[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_ClearPendingIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) NVIC->ICPR[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline void NVIC_SetPendingIRQ(IRQn_Type irq) {
  if ((int)irq >= 0) NVIC->ISPR[(unsigned)irq/32] = 1u << ((unsigned)irq%32);
}
static inline uint32_t NVIC_GetPendingIRQ(IRQn_Type irq) {
  return NVIC->ISPR[(unsigned)irq/32] >> ((unsigned)irq%32) & 1u;
}
static inline uint32_t NVIC_GetActive(IRQn_Type irq) {
  return NVIC->IABR[(unsigned)irq/32] >> ((unsigned)irq%32) & 1u;
}
/* Same storage as CMSIS core_cm3.h: system handlers live in SCB->SHP. */
static inline void NVIC_SetPriority(IRQn_Type irq, uint32_t priority) {
  uint8_t value = (uint8_t)(priority << (8u - __NVIC_PRIO_BITS));
  if ((int)irq < 0) SCB->SHP[((uint32_t)irq & 0xFu) - 4u] = value;
  else NVIC->IP[(uint32_t)irq] = value;
}
static inline uint32_t NVIC_GetPriority(IRQn_Type irq) {
  if ((int)irq < 0) return (uint32_t)SCB->SHP[((uint32_t)irq & 0xFu) - 4u] >> (8u - __NVIC_PRIO_BITS);
  return (uint32_t)NVIC->IP[(uint32_t)irq] >> (8u - __NVIC_PRIO_BITS);
}
static inline void NVIC_SetPriorityGrouping(uint32_t group) {
  SCB->AIRCR = (0x5FAu << SCB_AIRCR_VECTKEY_Pos) | ((group & 7u) << SCB_AIRCR_PRIGROUP_Pos);
}
static inline uint32_t NVIC_GetPriorityGrouping(void) {
  return (SCB->AIRCR & SCB_AIRCR_PRIGROUP_Msk) >> SCB_AIRCR_PRIGROUP_Pos;
}
static inline void NVIC_SystemReset(void) {
  __DSB();
  SCB->AIRCR = (0x5FAu << SCB_AIRCR_VECTKEY_Pos) | (SCB->AIRCR & SCB_AIRCR_PRIGROUP_Msk) | SCB_AIRCR_SYSRESETREQ_Msk;
  __DSB();
  for (;;) {}
}
static inline uint32_t SysTick_Config(uint32_t ticks) {
  if (ticks == 0 || ticks > 0x01000000u) return 1;
  SysTick->LOAD = ticks - 1u;
  NVIC_SetPriority(SysTick_IRQn, (1u << __NVIC_PRIO_BITS) - 1u);
  SysTick->VAL = 0;
  SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_TICKINT_Msk | SysTick_CTRL_ENABLE_Msk;
  return 0;
}

/* ---- System, pins and GPIO --------------------------------------------- */
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
  __I uint32_t IntStatus;
  __I uint32_t IO0IntStatR, IO0IntStatF;
  __O uint32_t IO0IntClr;
  __IO uint32_t IO0IntEnR, IO0IntEnF;
  uint32_t RESERVED0[3];
  __I uint32_t IO2IntStatR, IO2IntStatF;
  __O uint32_t IO2IntClr;
  __IO uint32_t IO2IntEnR, IO2IntEnF;
} LPC_GPIOINT_TypeDef;
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

/* ---- Timers, PWM, motor control PWM, QEI, RIT, WDT, RTC ----------------- */
typedef struct {
  __IO uint32_t IR, TCR, TC, PR, PC, MCR, MR0, MR1, MR2, MR3, CCR;
  __I uint32_t CR0, CR1; uint32_t RESERVED0[2]; __IO uint32_t EMR;
  uint32_t RESERVED1[12]; __IO uint32_t CTCR;
} LPC_TIM_TypeDef;
typedef struct {
  __IO uint32_t IR, TCR, TC, PR, PC, MCR, MR0, MR1, MR2, MR3, CCR;
  __I uint32_t CR0, CR1, CR2, CR3; uint32_t RESERVED0;
  __IO uint32_t MR4, MR5, MR6, PCR, LER; uint32_t RESERVED1[7];
  __IO uint32_t CTCR;
} LPC_PWM_TypeDef;
typedef struct {
  __I uint32_t MCCON; __O uint32_t MCCON_SET, MCCON_CLR;
  __I uint32_t MCCAPCON; __O uint32_t MCCAPCON_SET, MCCAPCON_CLR;
  __IO uint32_t MCTIM0, MCTIM1, MCTIM2, MCPER0, MCPER1, MCPER2;
  __IO uint32_t MCPW0, MCPW1, MCPW2, MCDEADTIME, MCCCP;
  __I uint32_t MCCR0, MCCR1, MCCR2;
  __I uint32_t MCINTEN; __O uint32_t MCINTEN_SET, MCINTEN_CLR;
  __I uint32_t MCCNTCON; __O uint32_t MCCNTCON_SET, MCCNTCON_CLR;
  __I uint32_t MCINTFLAG; __O uint32_t MCINTFLAG_SET, MCINTFLAG_CLR, MCCAP_CLR;
} LPC_MCPWM_TypeDef;
typedef struct {
  __O uint32_t QEICON; __I uint32_t QEISTAT; __IO uint32_t QEICONF;
  __I uint32_t QEIPOS; __IO uint32_t QEIMAXPOS, CMPOS0, CMPOS1, CMPOS2;
  __I uint32_t INXCNT; __IO uint32_t INXCMP, QEILOAD;
  __I uint32_t QEITIME, QEIVEL, QEICAP; __IO uint32_t VELCOMP, FILTER;
  uint32_t RESERVED0[998];
  __O uint32_t QEIIEC, QEIIES; __I uint32_t QEIINTSTAT, QEIIE;
  __O uint32_t QEICLR, QEISET;
} LPC_QEI_TypeDef;
typedef struct {
  __IO uint32_t RICOMPVAL, RIMASK; __IO uint8_t RICTRL; uint8_t RESERVED0[3];
  __IO uint32_t RICOUNTER;
} LPC_RIT_TypeDef;
typedef struct {
  __IO uint8_t WDMOD; uint8_t RESERVED0[3];
  __IO uint32_t WDTC; __O uint8_t WDFEED; uint8_t RESERVED1[3];
  __I uint32_t WDTV; __IO uint32_t WDCLKSEL;
} LPC_WDT_TypeDef;
typedef struct {
  __IO uint8_t ILR; uint8_t RESERVED0[7];
  __IO uint8_t CCR; uint8_t RESERVED1[3];
  __IO uint8_t CIIR; uint8_t RESERVED2[3];
  __IO uint8_t AMR; uint8_t RESERVED3[3];
  __I uint32_t CTIME0, CTIME1, CTIME2;
  __IO uint8_t SEC; uint8_t RESERVED4[3];
  __IO uint8_t MIN; uint8_t RESERVED5[3];
  __IO uint8_t HOUR; uint8_t RESERVED6[3];
  __IO uint8_t DOM; uint8_t RESERVED7[3];
  __IO uint8_t DOW; uint8_t RESERVED8[3];
  __IO uint16_t DOY; uint16_t RESERVED9;
  __IO uint8_t MONTH; uint8_t RESERVED10[3];
  __IO uint16_t YEAR; uint16_t RESERVED11;
  __IO uint32_t CALIBRATION;
  __IO uint32_t GPREG0, GPREG1, GPREG2, GPREG3, GPREG4;
  __IO uint8_t RTC_AUXEN; uint8_t RESERVED12[3];
  __IO uint8_t RTC_AUX; uint8_t RESERVED13[3];
  __IO uint8_t ALSEC; uint8_t RESERVED14[3];
  __IO uint8_t ALMIN; uint8_t RESERVED15[3];
  __IO uint8_t ALHOUR; uint8_t RESERVED16[3];
  __IO uint8_t ALDOM; uint8_t RESERVED17[3];
  __IO uint8_t ALDOW; uint8_t RESERVED18[3];
  __IO uint16_t ALDOY; uint16_t RESERVED19;
  __IO uint8_t ALMON; uint8_t RESERVED20[3];
  __IO uint16_t ALYEAR; uint16_t RESERVED21;
} LPC_RTC_TypeDef;

/* ---- Serial interfaces --------------------------------------------------- */
typedef struct {
  union { __I uint8_t RBR; __O uint8_t THR; __IO uint8_t DLL; uint32_t RESERVED0; };
  union { __IO uint8_t DLM; __IO uint32_t IER; };
  union { __I uint32_t IIR; __O uint8_t FCR; };
  __IO uint8_t LCR; uint8_t RESERVED1[7];
  __I uint8_t LSR; uint8_t RESERVED2[7];
  __IO uint8_t SCR; uint8_t RESERVED3[3];
  __IO uint32_t ACR;
  __IO uint8_t ICR; uint8_t RESERVED4[3];
  __IO uint8_t FDR; uint8_t RESERVED5[7];
  __IO uint8_t TER; uint8_t RESERVED6[39];
  __I uint8_t FIFOLVL;
} LPC_UART_TypeDef;
typedef struct {
  union { __I uint8_t RBR; __O uint8_t THR; __IO uint8_t DLL; uint32_t RESERVED0; };
  union { __IO uint8_t DLM; __IO uint32_t IER; };
  union { __I uint32_t IIR; __O uint8_t FCR; };
  __IO uint8_t LCR; uint8_t RESERVED1[3];
  __IO uint8_t MCR; uint8_t RESERVED2[3];
  __I uint8_t LSR; uint8_t RESERVED3[3];
  __I uint8_t MSR; uint8_t RESERVED4[3];
  __IO uint8_t SCR; uint8_t RESERVED5[3];
  __IO uint32_t ACR; uint32_t RESERVED6;
  __IO uint32_t FDR; uint32_t RESERVED7;
  __IO uint8_t TER; uint8_t RESERVED8[27];
  __IO uint8_t RS485CTRL; uint8_t RESERVED9[3];
  __IO uint8_t ADRMATCH; uint8_t RESERVED10[3];
  __IO uint8_t RS485DLY; uint8_t RESERVED11[3];
  __I uint8_t FIFOLVL;
} LPC_UART1_TypeDef;
typedef struct {
  __IO uint32_t CR0, CR1, DR; __I uint32_t SR; __IO uint32_t CPSR, IMSC, RIS, MIS, ICR, DMACR;
} LPC_SSP_TypeDef;
typedef struct {
  __IO uint32_t SPCR; __I uint32_t SPSR; __IO uint32_t SPDR, SPCCR;
  uint32_t RESERVED0[3]; __IO uint32_t SPINT;
} LPC_SPI_TypeDef;
typedef struct {
  __IO uint32_t I2CONSET; __I uint32_t I2STAT; __IO uint32_t I2DAT, I2ADR0;
  __IO uint32_t I2SCLH, I2SCLL; __O uint32_t I2CONCLR; __IO uint32_t MMCTRL;
  __IO uint32_t I2ADR1, I2ADR2, I2ADR3; __I uint32_t I2DATA_BUFFER;
  __IO uint32_t I2MASK0, I2MASK1, I2MASK2, I2MASK3;
} LPC_I2C_TypeDef;
typedef struct {
  __IO uint32_t I2SDAO, I2SDAI; __O uint32_t I2STXFIFO; __I uint32_t I2SRXFIFO, I2SSTATE;
  __IO uint32_t I2SDMA1, I2SDMA2, I2SIRQ, I2STXRATE, I2SRXRATE, I2STXBITRATE;
  __IO uint32_t I2SRXBITRATE, I2STXMODE, I2SRXMODE;
} LPC_I2S_TypeDef;

/* ---- Analog --------------------------------------------------------------- */
typedef struct {
  __IO uint32_t ADCR, ADGDR; uint32_t RESERVED0; __IO uint32_t ADINTEN;
  __IO uint32_t ADDR0, ADDR1, ADDR2, ADDR3, ADDR4, ADDR5, ADDR6, ADDR7;
  __IO uint32_t ADSTAT, ADTRM;
} LPC_ADC_TypeDef;
typedef struct {
  __IO uint32_t DACR, DACCTRL; __IO uint16_t DACCNTVAL;
} LPC_DAC_TypeDef;

/* ---- DMA (declared for compilation; not modeled) ------------------------- */
typedef struct {
  __I uint32_t DMACIntStat, DMACIntTCStat; __O uint32_t DMACIntTCClear;
  __I uint32_t DMACIntErrStat; __O uint32_t DMACIntErrClr;
  __I uint32_t DMACRawIntTCStat, DMACRawIntErrStat, DMACEnbldChns;
  __IO uint32_t DMACSoftBReq, DMACSoftSReq, DMACSoftLBReq, DMACSoftLSReq;
  __IO uint32_t DMACConfig, DMACSync;
} LPC_GPDMA_TypeDef;
typedef struct {
  __IO uint32_t DMACCSrcAddr, DMACCDestAddr, DMACCLLI, DMACCControl, DMACCConfig;
} LPC_GPDMACH_TypeDef;

#define LPC_WDT ((LPC_WDT_TypeDef *)0x40000000u)
#define LPC_TIM0 ((LPC_TIM_TypeDef *)0x40004000u)
#define LPC_TIM1 ((LPC_TIM_TypeDef *)0x40008000u)
#define LPC_UART0 ((LPC_UART_TypeDef *)0x4000C000u)
#define LPC_UART1 ((LPC_UART1_TypeDef *)0x40010000u)
#define LPC_PWM1 ((LPC_PWM_TypeDef *)0x40018000u)
#define LPC_I2C0 ((LPC_I2C_TypeDef *)0x4001C000u)
#define LPC_SPI ((LPC_SPI_TypeDef *)0x40020000u)
#define LPC_RTC ((LPC_RTC_TypeDef *)0x40024000u)
#define LPC_GPIOINT ((LPC_GPIOINT_TypeDef *)0x40028080u)
#define LPC_PINCON ((LPC_PINCON_TypeDef *)0x4002C000u)
#define LPC_SSP1 ((LPC_SSP_TypeDef *)0x40030000u)
#define LPC_ADC ((LPC_ADC_TypeDef *)0x40034000u)
#define LPC_I2C1 ((LPC_I2C_TypeDef *)0x4005C000u)
#define LPC_SSP0 ((LPC_SSP_TypeDef *)0x40088000u)
#define LPC_DAC ((LPC_DAC_TypeDef *)0x4008C000u)
#define LPC_TIM2 ((LPC_TIM_TypeDef *)0x40090000u)
#define LPC_TIM3 ((LPC_TIM_TypeDef *)0x40094000u)
#define LPC_UART2 ((LPC_UART_TypeDef *)0x40098000u)
#define LPC_UART3 ((LPC_UART_TypeDef *)0x4009C000u)
#define LPC_I2C2 ((LPC_I2C_TypeDef *)0x400A0000u)
#define LPC_I2S ((LPC_I2S_TypeDef *)0x400A8000u)
#define LPC_RIT ((LPC_RIT_TypeDef *)0x400B0000u)
#define LPC_MCPWM ((LPC_MCPWM_TypeDef *)0x400B8000u)
#define LPC_QEI ((LPC_QEI_TypeDef *)0x400BC000u)
#define LPC_SC ((LPC_SC_TypeDef *)0x400FC000u)
#define LPC_GPDMA ((LPC_GPDMA_TypeDef *)0x50004000u)
#define LPC_GPDMACH0 ((LPC_GPDMACH_TypeDef *)0x50004100u)
#define LPC_GPIO0 ((LPC_GPIO_TypeDef *)0x2009C000u)
#define LPC_GPIO1 ((LPC_GPIO_TypeDef *)0x2009C020u)
#define LPC_GPIO2 ((LPC_GPIO_TypeDef *)0x2009C040u)
#define LPC_GPIO3 ((LPC_GPIO_TypeDef *)0x2009C060u)
#define LPC_GPIO4 ((LPC_GPIO_TypeDef *)0x2009C080u)

extern uint32_t SystemCoreClock;
void SystemInit(void);
void SystemCoreClockUpdate(void);
#endif
