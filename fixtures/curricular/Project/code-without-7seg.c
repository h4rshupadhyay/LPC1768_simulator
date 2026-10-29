#include <LPC17xx.h>
#include <stdbool.h>

/* ===================================================
 * SMART MULTI-BASE CALCULATOR — LPC1768
 * Supports BIN, BASE4, OCT, DEC, HEX with
 * keypad and LCD (no 7-segment).
 *
 * Features:
 *  • SysTick 1 ms hardware timing
 *  • HEX: double MODE press <2 s → operator mode
 *  • Signed decimal arithmetic; modular in other bases
 * ===================================================
 */

/* ===== Pin & Mode Defines ===== */
#define COL_BASE 15
#define ROW_BASE 19
#define COL_MASK (0x0F << COL_BASE)
#define ROW_MASK (0x0F << ROW_BASE)

#define LCD_DATA_SHIFT 23
#define LCD_DATA_MASK (0x0F << LCD_DATA_SHIFT)
#define LCD_RS (1 << 27)
#define LCD_EN (1 << 28)

#define MODE_BUTTON (1 << 12)

/* Modes / Bases */
#define MODE_BIN   2
#define MODE_BASE4 4
#define MODE_OCT   8
#define MODE_DEC   10
#define MODE_HEX   16

/* Operators */
#define OP_NONE 0
#define OP_ADD  1
#define OP_SUB  2
#define OP_MUL  3
#define OP_CLR  4
#define OP_RES  5

/* ===== Globals ===== */
int input_num, stored_num, result;
unsigned int operation;
unsigned int current_base;

unsigned char hex_op_mode;
unsigned char result_displayed;

unsigned int key, last_key, stable;
unsigned int button_state, last_button_state, button_stable;

unsigned long last_mode_press_time;

/* ===== System tick counter ===== */
volatile unsigned long sys_millis = 0;

/* ===== Forward Declarations ===== */
void delay(volatile unsigned int d);
void lcd_delay(unsigned long r);
void lcd_write_nibble(unsigned char nibble, unsigned char is_data);
void lcd_cmd(unsigned char cmd);
void lcd_data(unsigned char data);
void lcd_init(void);
void lcd_print_str(const char *s);
void lcd_print_num(int num, unsigned int base);
void display_mode(void);
void display_input(void);
void display_result(void);
unsigned int scan_keypad(void);
unsigned int scan_mode_button(void);
unsigned int is_valid_digit(unsigned int key);
void change_mode(void);
void handle_mode_button(void);
void operate(unsigned int op);
void perform_operation(void);
unsigned char is_operator_active(unsigned int key);
int base_arith(int a, int b, unsigned int op, unsigned int base);
unsigned long millis(void);

/* =================================================== */
/* ===== Implementation                               */
/* =================================================== */

void delay(volatile unsigned int d){ while(d--) __NOP(); }
void lcd_delay(unsigned long r){ volatile unsigned long i; for(i=0;i<r;i++); }

/* ---- SysTick (1 ms) ---- */
void SysTick_Handler(void){ sys_millis++; }
unsigned long millis(void){ return sys_millis; }

/* ---- LCD primitives ---- */
void lcd_write_nibble(unsigned char nibble, unsigned char is_data){
    unsigned long temp = (nibble & 0x0F) << LCD_DATA_SHIFT;
    LPC_GPIO0->FIOPIN = (LPC_GPIO0->FIOPIN & ~LCD_DATA_MASK) | temp;
    if(is_data) LPC_GPIO0->FIOSET = LCD_RS; else LPC_GPIO0->FIOCLR = LCD_RS;
    LPC_GPIO0->FIOSET = LCD_EN; lcd_delay(100);
    LPC_GPIO0->FIOCLR = LCD_EN; lcd_delay(250000);
}
void lcd_cmd(unsigned char c){ lcd_write_nibble(c>>4,0); lcd_write_nibble(c,0); }
void lcd_data(unsigned char d){ lcd_write_nibble(d>>4,1); lcd_write_nibble(d,1); }

void lcd_init(void){
    lcd_delay(5000000);
    lcd_write_nibble(0x03,0); lcd_delay(500000);
    lcd_write_nibble(0x03,0); lcd_delay(500000);
    lcd_write_nibble(0x03,0); lcd_delay(500000);
    lcd_write_nibble(0x02,0); lcd_delay(500000);
    lcd_cmd(0x28); lcd_cmd(0x0C); lcd_cmd(0x01); lcd_delay(500000); lcd_cmd(0x06);
}

void lcd_print_str(const char *s){ while(*s) lcd_data(*s++); }

void lcd_print_num(int num, unsigned int base){
    char buf[17]; int i=0; unsigned int unum;

    if(base==MODE_DEC && num<0){ lcd_data('-'); num=-num; }
    unum=(unsigned int)num;
    if(unum==0){ lcd_data('0'); return; }

    while(unum>0 && i<16){
        unsigned int d=unum%base;
        buf[i++]=(d<10)?('0'+d):('A'+d-10);
        unum/=base;
    }
    while(i>0) lcd_data(buf[--i]);
}

/* ---- Display helpers ---- */
void display_mode(void){
    lcd_cmd(0x80);
    lcd_print_str("Mode: ");
    if(current_base==MODE_BIN) lcd_print_str("BIN   ");
    else if(current_base==MODE_BASE4) lcd_print_str("BASE4 ");
    else if(current_base==MODE_OCT) lcd_print_str("OCT   ");
    else if(current_base==MODE_DEC) lcd_print_str("DEC   ");
    else { lcd_print_str("HEX");
           if(hex_op_mode) lcd_print_str("[OPS]");
           else lcd_print_str("    "); }
}

void display_input(void){
    lcd_cmd(0xC0);
    lcd_print_str("Input: ");
    lcd_print_num(input_num,current_base);
    lcd_print_str("      ");
}

void display_result(void){
    lcd_cmd(0xC0);
    lcd_print_str("Result: ");
    lcd_print_num(result,current_base);
    lcd_print_str("      ");
}

/* ---- Keypad scanning ---- */
unsigned int scan_keypad(void){
    unsigned int col,row,row_bits;
    for(col=0;col<4;col++){
        LPC_GPIO0->FIOSET=COL_MASK; delay(50);
        LPC_GPIO0->FIOCLR=(1<<(COL_BASE+col)); delay(200);
        row_bits=(LPC_GPIO0->FIOPIN&ROW_MASK)>>ROW_BASE;
        if(row_bits!=0x0F){
            for(row=0;row<4;row++)
                if(!(row_bits&(1<<row))){ LPC_GPIO0->FIOSET=COL_MASK; return col*4+row; }
        }
    }
    LPC_GPIO0->FIOSET=COL_MASK;
    return 0xFF;
}

/* ---- MODE button ---- */
unsigned int scan_mode_button(void){
    return ((LPC_GPIO2->FIOPIN&MODE_BUTTON)==0)?1:0;
}

void change_mode(void){
    if(current_base==MODE_DEC) current_base=MODE_BIN;
    else if(current_base==MODE_BIN) current_base=MODE_BASE4;
    else if(current_base==MODE_BASE4) current_base=MODE_OCT;
    else if(current_base==MODE_OCT) current_base=MODE_HEX;
    else current_base=MODE_DEC;

    input_num=stored_num=result=0;
    operation=OP_NONE; result_displayed=0;
    display_mode(); display_input();
}

/* ---- Double-press / mode handler ---- */
void handle_mode_button(void){
    unsigned long now=millis();
    if(button_stable==3 && button_state==1){
        if(current_base==MODE_HEX){
            if((now-last_mode_press_time)<2000){
                hex_op_mode=!hex_op_mode;
                display_mode(); last_mode_press_time=0;
            } else last_mode_press_time=now;
        } else change_mode();
    }
}

/* ---- Validation ---- */
unsigned int is_valid_digit(unsigned int key){
    if(key>=16) return 0;
    if(current_base==MODE_BIN   && key>=2)  return 0;
    if(current_base==MODE_BASE4 && key>=4)  return 0;
    if(current_base==MODE_OCT   && key>=8)  return 0;
    if(current_base==MODE_DEC   && key>=10) return 0;
    return 1;
}

/* ---- Arithmetic core ---- */
int base_arith(int a,int b,unsigned int op,unsigned int base){
    int r=0;
    switch(op){
        case OP_ADD: r=a+b; break;
        case OP_SUB: r=a-b; break;
        case OP_MUL: r=a*b; break;
        default: r=a; break;
    }

    if(base!=MODE_DEC){           /* wrap-around for others */
        if(r<0) r=((r%base)+base)%base;
        else    r%= (base*base*base*base);  /* loose limit */
    }
    return r;
}

/* ---- Operator control ---- */
void operate(unsigned int op){ stored_num=input_num; input_num=0; operation=op; result_displayed=0; }
void perform_operation(void){
    result=base_arith(stored_num,input_num,operation,current_base);
    display_result();
    input_num=result; operation=OP_NONE; result_displayed=1;
}

unsigned char is_operator_active(unsigned int key){
    if(key>=11 && key<=15){
        if(current_base==MODE_HEX) return hex_op_mode;
        else return 1;
    }
    return 0;
}

/* =================================================== */
/* ===================== MAIN ======================== */
/* =================================================== */
int main(void){
    current_base=MODE_DEC;
    input_num=stored_num=result=0;
    operation=OP_NONE; result_displayed=0;
    key=last_key=0xFF; stable=0;
    button_stable=0; button_state=last_button_state=0;
    hex_op_mode=0; last_mode_press_time=0;

    SystemCoreClockUpdate();
    SysTick_Config(SystemCoreClock/1000);   // 1 ms tick

    /* GPIO mux: make pins GPIO */
    LPC_PINCON->PINSEL0=0; LPC_PINCON->PINSEL1=0;
    LPC_PINCON->PINSEL3=0; LPC_PINCON->PINSEL4=0;
    LPC_PINCON->PINSEL0 &= ~0xFFF00000;     // P0.4–P0.11 as GPIO

    /* Directions: keypad columns out, rows in; LCD pins out; MODE button in */
    LPC_GPIO0->FIODIR |= COL_MASK | LCD_DATA_MASK | LCD_RS | LCD_EN;
    LPC_GPIO0->FIODIR &= ~ROW_MASK;
    LPC_GPIO0->FIOSET  = COL_MASK;

    LPC_GPIO2->FIODIR &= ~MODE_BUTTON;

    lcd_init(); display_mode(); display_input();

    while(1){
        key=scan_keypad();
        button_state=scan_mode_button();

        if(key==last_key) stable=(stable<5)?stable+1:stable;
        else{ last_key=key; stable=0; }

        if(button_state==last_button_state)
            button_stable=(button_stable<5)?button_stable+1:button_stable;
        else{ last_button_state=button_state; button_stable=0; }

        handle_mode_button();

        if(stable==3 && key!=0xFF){
            if(is_operator_active(key)){
                switch(key){
                    case 11: operate(OP_ADD); display_input(); break;
                    case 12: input_num=stored_num=result=0;
                             operation=OP_NONE; display_input(); break;
                    case 13: operate(OP_SUB); display_input(); break;
                    case 14: operate(OP_MUL); display_input(); break;
                    case 15: perform_operation(); break;
                }
            } else if(is_valid_digit(key)){
                result_displayed=0;
                input_num=input_num*current_base+key;
                display_input();
            }
            stable=5;
        }

        /* Small idle delay; adjust as desired */
        delay(3000);
    }
}
