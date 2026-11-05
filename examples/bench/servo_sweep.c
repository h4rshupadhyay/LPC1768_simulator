/* SG90 servo sweep on the ALS kit: signal on CND.7 (P2.0 = PWM1.1),
 * servo powered from the kit's 5 V tap. 50 Hz frame, 1.0-2.0 ms pulses.
 */
#include <LPC17xx.h>

int main(void)
{
    SystemInit();
    LPC_PINCON->PINSEL4 = (LPC_PINCON->PINSEL4 & ~3u) | 1u;   /* P2.0 PWM1.1 */
    LPC_PWM1->PR = SystemCoreClock / 4 / 1000000 - 1;          /* 1 us per count */
    LPC_PWM1->MR0 = 20000;                                     /* 20 ms period */
    LPC_PWM1->MR1 = 1500;
    LPC_PWM1->MCR = 3;                                         /* flag (MR0I) and reset on MR0 */
    LPC_PWM1->PCR = 1u << 9;                                   /* enable PWM1.1 output */
    LPC_PWM1->LER = 3;
    LPC_PWM1->TCR = 9;                                         /* counter + PWM enable */
    unsigned width = 1000;
    int step = 20;
    while (1) {
        while (!(LPC_PWM1->IR & 1)) {}                         /* wait for the frame boundary */
        LPC_PWM1->IR = 1;
        LPC_PWM1->MR1 = width;
        LPC_PWM1->LER = 2;
        width += step;
        if (width >= 2000 || width <= 1000) step = -step;
    }
}
