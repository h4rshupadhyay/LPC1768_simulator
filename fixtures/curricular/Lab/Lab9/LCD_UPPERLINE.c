#include <LPC17xx.h>

#define RS_CTRL 0x08000000
#define EN_CTRL 0x10000000
#define DT_CTRL 0x07800000

unsigned long int temp1 = 0, temp2 = 0, i, j;
unsigned char flag1 = 0, flag2 = 0;
unsigned char msg[] = ("We have fun.");

void lcd_write(void);
void port_write(void);
void delay_lcd(unsigned long);

unsigned long int init_command[] = {0x30, 0x30, 0x30, 0x20, 0x28, 0x0C, 0x01, 0x80};

int main() {
    LPC_GPIO0->FIODIR = DT_CTRL | RS_CTRL | EN_CTRL;

    flag1 = 0;

    for (i = 0; i < 8; i++) {
        temp1 = init_command[i];
        lcd_write();
    }

		flag1=1;

		i= 0;

		while(msg[i]!='\0'){
			temp1=msg[i];
			i++;
			lcd_write();
		}
    while (1);
}

void lcd_write(void) {
    flag2 = (flag1 == 1) ? 0 : (((temp1 == 0x30) || (temp1 == 0x20)) ? 1 : 0);

    temp2 = temp1 & 0xf0;
    temp2 = temp2 << 19;

    port_write();

    if (!flag2) {
        temp2 = temp1 & 0x0f;
        temp2 = temp2 << 23;
        port_write();
    }
}

void port_write(void) {
    LPC_GPIO0->FIOPIN = temp2;

    if (flag1 == 0) {
        LPC_GPIO0->FIOCLR = RS_CTRL;
    } else {
        LPC_GPIO0->FIOSET = RS_CTRL;
    }

    LPC_GPIO0->FIOSET = EN_CTRL;
    delay_lcd(100);
    LPC_GPIO0->FIOCLR = EN_CTRL;

    delay_lcd(500000);
}

void delay_lcd(unsigned long r1) {
    unsigned long r;

    for (r = 0; r < r1; r++)
        ;
    return;
}
