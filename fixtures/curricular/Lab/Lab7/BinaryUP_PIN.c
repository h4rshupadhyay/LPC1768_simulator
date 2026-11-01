// Question - WAP in EC to display 8 bit UP counter on the port pin 0.4 to 0.11

#include <LPC17xx.h>

int main(){
	unsigned char x = 0;
	int i = 0;
	
	LPC_PINCON -> PINSEL0 = 0x0000<<8 ;
	LPC_GPIO0 -> FIODIR = 0xFF<<4;
	
	while(1){
		LPC_GPIO0 -> FIOPIN = x << 4;
		x = (x+1)%256;
		for(i = 0; i < 50000; i++);
	}
}