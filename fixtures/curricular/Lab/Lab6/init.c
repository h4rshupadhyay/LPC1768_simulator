// Embedded C Programming
// 5 Ports
// Each Port has 32 pins (PX0.31)
// Each Port has 2 PINSEL (0-15, 16-31)

#include <LPC17xx.h>

int main(){
	int i; // variable declarations have to be global
	LPC_PINCON->PINSEL0 &= 0xFF0000FF;
	LPC_GPIO0->FIODIR = 0x00000FF0;
	
	while(1){
	LPC_GPIO0-> FIOSET=0x00000FF0;
	for(i=0; i<1000; i++); //delay
	LPC_GPIO0->FIOCLR=0x00000FF0;
	for(i=0; i<1000; i++); //delay
	}
}
