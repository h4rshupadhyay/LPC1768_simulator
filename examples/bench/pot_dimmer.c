/* Bare LPC1768: potentiometer on AD0.0 (P0.23) sets the brightness of an LED on
 * PWM1.1 (P2.0, 330 Ohm resistor). The ADC reading prints on UART0 (9600 baud).
 */
#include <LPC17xx.h>

static void uart0_init(void)
{
    LPC_PINCON->PINSEL0 = (LPC_PINCON->PINSEL0 & ~0xF0u) | 0x50u;
    LPC_UART0->LCR = 0x83;
    unsigned divisor = SystemCoreClock / 4 / (16 * 9600);
    LPC_UART0->DLL = divisor & 0xFF;
    LPC_UART0->DLM = divisor >> 8;
    LPC_UART0->LCR = 0x03;
}
static void putc0(char c) { while (!(LPC_UART0->LSR & 0x20)) {} LPC_UART0->THR = c; }
static void putu(unsigned v)
{
    char buffer[11]; int i = 10; buffer[i] = 0;
    do { buffer[--i] = '0' + v % 10; v /= 10; } while (v);
    while (buffer[i]) putc0(buffer[i++]);
}

static unsigned adc_read(void)
{
    LPC_ADC->ADCR = (LPC_ADC->ADCR & ~0xFFu) | 1u | (1u << 24);   /* channel 0, start now */
    while (!(LPC_ADC->ADGDR & (1u << 31))) {}
    return (LPC_ADC->ADGDR >> 4) & 0xFFF;
}

int main(void)
{
    SystemInit();
    uart0_init();
    LPC_SC->PCONP |= 1u << 12;                                     /* ADC power */
    LPC_PINCON->PINSEL1 = (LPC_PINCON->PINSEL1 & ~(3u << 14)) | (1u << 14);  /* P0.23 AD0.0 */
    LPC_PINCON->PINMODE1 = (LPC_PINCON->PINMODE1 & ~(3u << 14)) | (2u << 14); /* no pull on the analog pin */
    LPC_ADC->ADCR = (4u << 8) | (1u << 21);                        /* 25 MHz / 5 = 5 MHz, PDN */

    LPC_PINCON->PINSEL4 = (LPC_PINCON->PINSEL4 & ~3u) | 1u;        /* P2.0 PWM1.1 */
    LPC_PWM1->MR0 = 4096;
    LPC_PWM1->MCR = 2;
    LPC_PWM1->PCR = 1u << 9;
    LPC_PWM1->LER = 3;
    LPC_PWM1->TCR = 9;
    unsigned printed = 0;
    while (1) {
        unsigned value = adc_read();
        LPC_PWM1->MR1 = value;
        LPC_PWM1->LER = 2;
        if (++printed % 2000 == 1) { putu(value); putc0('\r'); putc0('\n'); }
    }
}
