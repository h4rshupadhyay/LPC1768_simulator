/* Corrected lab reference. See docs/BOARD_NOTES.md; original PDFs are unchanged. */
#include <LPC17xx.h>

void delay(unsigned n) { volatile unsigned i; for(i=0;i<n;i++); }
void setup(void) { SystemInit(); SystemCoreClockUpdate(); }
void leds_init(void) { LPC_PINCON->PINSEL0 &= 0xFF0000FF; LPC_GPIO0->FIODIR |= 0xFF0; }
void leds(unsigned v) { LPC_GPIO0->FIOCLR=0xFF0; LPC_GPIO0->FIOSET=(v&255)<<4; }
unsigned switch_up(void) { return (LPC_GPIO2->FIOPIN >> 12)&1; }
void lcd_nibble(unsigned v,unsigned rs) {
  LPC_GPIO0->FIOPIN=(v<<23)|(rs<<27);
  LPC_GPIO0->FIOSET=1<<28; delay(4); LPC_GPIO0->FIOCLR=1<<28;
}
void lcd_byte(unsigned v,unsigned rs) { lcd_nibble(v>>4,rs); lcd_nibble(v&15,rs); }
void lcd_init(void) {
  LPC_PINCON->PINSEL1 &= ~0x03FFC000;
  LPC_GPIO0->FIODIR |= 0x1F800000;
  lcd_nibble(3,0); lcd_nibble(3,0); lcd_nibble(3,0); lcd_nibble(2,0);
  lcd_byte(0x28,0); lcd_byte(0x0C,0); lcd_byte(0x06,0); lcd_byte(1,0);
}
void lcd_text(const char *s) { while(*s) lcd_byte(*s++,1); }
void lcd_at(unsigned addr) { lcd_byte(0x80|addr,0); }
void lcd_number(int number) {
  char digits[12]; unsigned i=0,n;
  if(number<0) {lcd_byte('-',1); n=(unsigned)(-number);} else n=(unsigned)number;
  do { digits[i++]=(char)('0'+n%10); n/=10; } while(n);
  while(i) lcd_byte(digits[--i],1);
}
void keypad_init(void) {
  LPC_PINCON->PINSEL3 &= 0xFFC03FFF;
  LPC_PINCON->PINSEL4 &= 0xF00FFFFF;
  LPC_GPIO2->FIODIR |= 0x3C00; LPC_GPIO1->FIODIR &= ~0x07800000;
}
int keypad_read(void) {
  unsigned row,col,bits;
  for(row=0;row<4;row++) {
    LPC_GPIO2->FIOCLR=0x3C00; LPC_GPIO2->FIOSET=1<<(10+row);
    bits=(LPC_GPIO1->FIOPIN>>23)&15;
    for(col=0;col<4;col++) if(bits&(1<<col)) return (int)(row*4+col);
  } return -1;
}
const unsigned patterns[16]={0x3F,0x06,0x5B,0x4F,0x66,0x6D,0x7D,0x07,
  0x7F,0x6F,0x77,0x7C,0x39,0x5E,0x79,0x71};
void seg_init(void) {
  leds_init(); LPC_PINCON->PINSEL3 &= 0xFFC03FFF; LPC_GPIO1->FIODIR |= 0x07800000;
}
void seg_scan(unsigned value,unsigned radix) {
  unsigned d;
  for(d=0;d<4;d++) {
    LPC_GPIO1->FIOPIN=d<<23; LPC_GPIO0->FIOPIN=patterns[value%radix]<<4;
    delay(40); LPC_GPIO0->FIOCLR=0xFF0; LPC_GPIO1->FIOPIN=5<<23;
    value/=radix;
  }
}
void timer_init(void) {
  LPC_SC->PCONP |= 2; LPC_TIM0->TCR=2; LPC_TIM0->PR=99;
  LPC_TIM0->MR0=1000; LPC_TIM0->MCR=3; LPC_TIM0->TCR=1;
}
unsigned timer_elapsed(void) { if(LPC_TIM0->IR&1) {LPC_TIM0->IR=1; return 1;} return 0; }
void adc_init(void) {
  LPC_SC->PCONP |= 1<<12; LPC_PINCON->PINSEL3 |= 0xF0000000;
  LPC_PINCON->PINMODE3 = (LPC_PINCON->PINMODE3 & ~0xF0000000) | 0xA0000000;
}
unsigned adc_read(unsigned channel) {
  unsigned v; LPC_ADC->ADCR=(1<<channel)|(1u<<8)|(1<<21)|(1<<24);
  do {v=LPC_ADC->ADGDR;} while(!(v&(1u<<31))); return (v>>4)&4095;
}

int main(void) {int a,b,d,previous=5000;setup();lcd_init();adc_init();lcd_text("POT4 minus POT1");
 while(1) {a=adc_read(4);b=adc_read(5);d=a-b;
 /* Redraw on a changed reading; repeatedly clearing the same line flickers. */
 if(d!=previous) {lcd_at(0x40);lcd_text("                ");lcd_at(0x40);lcd_number(d);lcd_text(" counts");previous=d;}
 delay(4000);} }
