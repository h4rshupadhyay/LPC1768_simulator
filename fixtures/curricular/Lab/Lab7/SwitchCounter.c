// Question - Connect a key on P1.23 and LEDs on P0.4-0.11. WAP in EC to display the number of times the PUSH to OFF switch is pressed on LEDs.
#include <LPC17xx.h>

int main(){
	unsigned long x, count = 0;
	
	LPC_PINCON -> PINSEL0 = 0x0000<<8 ; 				// LED
	LPC_PINCON -> PINSEL3 = 0; 							// SWITCH
	
	LPC_GPIO0 -> FIODIR = 0xFF<<4;						// LED
	LPC_GPIO1 -> FIODIR = 0 << 23;						// SWITCH
	
	while(1){
		x = LPC_GPIO1 -> FIOPIN & 1 << 23; 				// Initial value to refer to
		if(!x){
			count = (count + 1)%255;  					// Counter
			LPC_GPIO0 -> FIOPIN = count << 4; 			// Modifying FIOPIN value to match count
			
	}
}
}
