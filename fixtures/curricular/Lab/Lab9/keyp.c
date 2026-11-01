#include <LPC17xx.h>

#define RS_CTRL 0x08000000
#define EN_CTRL 0x10000000
#define DT_CTRL 0x07800000

#define COL_BASE_BIT    15
#define ROW_BASE_BIT    19
#define COL_MASK ((0x0F) << COL_BASE_BIT)
#define ROW_MASK ((0x0F) << ROW_BASE_BIT)

unsigned long int temp1 = 0, temp2 = 0, i;
unsigned char flag1 = 0, flag2 = 0;

unsigned long int init_command[] = {
    0x30, 0x30, 0x30, 0x20, 0x28, 0x0C, 0x01, 0x80
};

const unsigned char key_chars[16] = {
    '0','1','2','3','4','5','6','7',
    '8','9','A','B','C','D','E','F'
};

void lcd_write(void);
void port_write(void);
void delay_lcd(unsigned long);
void short_delay(volatile unsigned int d);
void lcd_display_key(unsigned char key);

int main(void) {
    unsigned int col_idx, row_idx;
    unsigned int candidate = 0xFF;
    unsigned int stable = 0;
    unsigned int displayed = 0xFF;
    unsigned int row_bits;

    LPC_PINCON->PINSEL0 &= ~(0xFFFFFFFF);
    LPC_PINCON->PINSEL1 &= ~(0xFFFFFFFF);

    LPC_GPIO0->FIODIR = DT_CTRL | RS_CTRL | EN_CTRL;
    LPC_GPIO0->FIODIR |= COL_MASK;
    LPC_GPIO0->FIODIR &= ~ROW_MASK;

    LPC_GPIO0->FIOSET = COL_MASK;

    flag1 = 0;
    for (i = 0; i < 8; i++) {
        temp1 = init_command[i];
        lcd_write();
    }

    flag1 = 0;
    temp1 = 0x80;
    lcd_write();

    flag1 = 1;
    temp1 = 'K';
    lcd_write();
    temp1 = 'e';
    lcd_write();
    temp1 = 'y';
    lcd_write();
    temp1 = ':';
    lcd_write();
    temp1 = ' ';
    lcd_write();

    for(;;) {
        unsigned int read_key = 0xFF;

        for(col_idx = 0; col_idx < 4; col_idx++) {
            LPC_GPIO0->FIOSET = COL_MASK;
            short_delay(50);
            LPC_GPIO0->FIOCLR = (1 << (COL_BASE_BIT + col_idx));
            short_delay(200);

            row_bits = (LPC_GPIO0->FIOPIN & ROW_MASK) >> ROW_BASE_BIT;

            if(row_bits != 0x0F) {
                for(row_idx = 0; row_idx < 4; row_idx++) {
                    if((row_bits & (1 << row_idx)) == 0) {
                        read_key = col_idx * 4 + row_idx;
                        break;
                    }
                }
                LPC_GPIO0->FIOSET = COL_MASK;
                break;
            }
            LPC_GPIO0->FIOSET = COL_MASK;
        }

        if(read_key == candidate) {
            if(stable < 3) stable++;
        } else {
            candidate = read_key;
            stable = 1;
        }

        if(stable >= 3) {
            if(candidate != 0xFF && candidate != displayed) {
                displayed = candidate;
                lcd_display_key(displayed);
            }
            stable = 3;
        }

        short_delay(3000);
    }
}

void lcd_display_key(unsigned char key) {
    flag1 = 0;
    temp1 = 0x85;
    lcd_write();

    flag1 = 1;
    temp1 = key_chars[key];
    lcd_write();
}

void short_delay(volatile unsigned int d) {
    while(d--) __NOP();
}

void lcd_write(void) {
    flag2 = (flag1 == 1) ? 0 :
            (((temp1 == 0x30) || (temp1 == 0x20)) ? 1 : 0);

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
    for (r = 0; r < r1; r++);
    return;
}
