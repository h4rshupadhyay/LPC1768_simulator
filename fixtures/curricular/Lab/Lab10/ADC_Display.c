#include <LPC17xx.h>
#include <stdio.h>

#define RS_CTRL 0x08000000
#define EN_CTRL 0x10000000
#define DT_CTRL 0x07800000

unsigned long result, y, m;
unsigned long int temp1 = 0, temp2 = 0, i;
unsigned char flag1 = 0, flag2 = 0;
unsigned char msg[20];

void lcd_write(void);
void port_write(void);
void delay_lcd(unsigned long);
void lcd_init(void);
void lcd_print(unsigned char *);
void lcd_clear(void);
void ADC_IRQHandler(void);
void ADC_init(void);

int main(void) {
    LPC_GPIO0->FIODIR = DT_CTRL | RS_CTRL | EN_CTRL; // LCD pins as output

    lcd_init();  // Initialize LCD
    lcd_print((unsigned char *)"ADC Val:"); // Idle message

    ADC_init();  // Initialize ADC

    while (1) {
        // idle loop
    }
}

void ADC_init(void) {
    LPC_PINCON->PINSEL3 = 3 << 28;  // P1.30 as AD0.4
    LPC_SC->PCONP |= 1 << 12;        // Power to ADC
    LPC_ADC->ADCR = (1 << 4) | (1 << 21) | (1 << 16); // select AD0.4, burst mode, enable
    LPC_ADC->ADINTEN = (1 << 4);    // Enable interrupt for AD0.4
    NVIC_EnableIRQ(ADC_IRQn);
}

void ADC_IRQHandler(void) {
    result = (LPC_ADC->ADGDR >> 4) & 0xFFF; // 12-bit ADC result

    lcd_clear();
    lcd_print((unsigned char *)"ADC Val:");
    sprintf((char *)msg, " %lu", result);
    lcd_print(msg);

    y = (LPC_ADC->ADDR4 >> 4) & 0xFFF; // clear done flag

		for(m=0;m<1000000;m++);
}

void lcd_init(void) {
    unsigned long int init_command[] =
        {0x30, 0x30, 0x30, 0x20, 0x28, 0x0C, 0x01, 0x80};

    flag1 = 0;
    for (i = 0; i < 8; i++) {
        temp1 = init_command[i];
        lcd_write();
    }
    flag1 = 1;
    delay_lcd(5000);
}

void lcd_print(unsigned char *text) {
    unsigned int j = 0;
    while (text[j] != '\0') {
        temp1 = text[j];
        lcd_write();
        j++;
    }
}

void lcd_clear(void) {
    flag1 = 0;
    temp1 = 0x01; // clear command
    lcd_write();
    delay_lcd(5000);
    flag1 = 1;
}

void lcd_write(void) {
    flag2 = (flag1 == 1) ? 0 : (((temp1 == 0x30) || (temp1 == 0x20)) ? 1 : 0);

    temp2 = temp1 & 0xF0;
    temp2 = temp2 << 19;
    port_write();

    if (!flag2) {
        temp2 = temp1 & 0x0F;
        temp2 = temp2 << 23;
        port_write();
    }
}

void port_write(void) {
    LPC_GPIO0->FIOPIN = temp2;

    if (flag1 == 0)
        LPC_GPIO0->FIOCLR = RS_CTRL;
    else
        LPC_GPIO0->FIOSET = RS_CTRL;

    LPC_GPIO0->FIOSET = EN_CTRL;
    delay_lcd(100);
    LPC_GPIO0->FIOCLR = EN_CTRL;
    delay_lcd(50000);
}

void delay_lcd(unsigned long r1) {
    unsigned long r;
    for (r = 0; r < r1; r++);
}
