/* Walking segment test. Connect CNA -> CNA2 and CNB -> CNB2.
 * On the leftmost digit, a, b, c, d, e, f, g and dp light in turn,
 * each for 250 ms, then repeat. Check both ribbons if nothing appears.
 * This tests the simulated digital wiring, not LED current or brightness.
 */
#include <LPC17xx.h>

#define SEGMENT_MASK (0xFFu << 4)  /* P0.4-P0.11: a, b, c, d, e, f, g, dp */
#define DIGIT_MASK (0xFu << 23)    /* P1.23-P1.26: U7 decoder address */

static void setup(void) {
    SystemInit();
    SystemCoreClockUpdate();
    LPC_PINCON->PINSEL0 &= ~0x00FFFF00u;
    LPC_PINCON->PINSEL3 &= ~0x003FC000u;
    LPC_GPIO0->FIODIR |= SEGMENT_MASK;
    LPC_GPIO1->FIODIR |= DIGIT_MASK;
    LPC_GPIO1->FIOSET = DIGIT_MASK; /* address 15: all digits off */
    LPC_GPIO0->FIOCLR = SEGMENT_MASK;

    /* Standard startup: CCLK = 100 MHz, Timer0 PCLK = CCLK / 4. */
    LPC_SC->PCONP |= 1u << 1;
    LPC_SC->PCLKSEL0 &= ~(3u << 2);
    LPC_TIM0->TCR = 2;              /* reset timer and prescaler */
    LPC_TIM0->PR = SystemCoreClock / 4u / 1000u - 1u; /* 1 ms tick */
    LPC_TIM0->MCR = 3;              /* set IR0 and reset TC on match */
    LPC_TIM0->IR = 0xFF;            /* clear old flags (write one to clear) */
}

static void wait_ms(unsigned ms) {
    LPC_TIM0->TCR = 2;
    LPC_TIM0->MR0 = ms;
    LPC_TIM0->IR = 1;
    LPC_TIM0->TCR = 1;
    while (!(LPC_TIM0->IR & 1u)) { }
    LPC_TIM0->IR = 1;               /* acknowledge match */
    LPC_TIM0->TCR = 0;
}

static void show(unsigned digit, unsigned segments) {
    LPC_GPIO1->FIOSET = DIGIT_MASK; /* blank before changing segments */
    LPC_GPIO0->FIOCLR = SEGMENT_MASK;
    LPC_GPIO0->FIOSET = (segments & 0xFFu) << 4;
    /* One write selects the address without a temporary digit-0 selection. */
    LPC_GPIO1->FIOPIN = (LPC_GPIO1->FIOPIN & ~DIGIT_MASK) | ((digit & 15u) << 23);
}

int main(void) {
    unsigned segment;
    setup();
    while (1) {
        for (segment = 0; segment < 8; ++segment) {
            show(3, 1u << segment);
            wait_ms(250);
        }
    }
}
