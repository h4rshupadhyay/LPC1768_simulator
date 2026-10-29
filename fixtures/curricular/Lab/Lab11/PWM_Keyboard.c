#include <LPC17xx.h>

// Global variable to store PWM value
unsigned long pwm_value = 0;

// Function to initialize PWM (Pulse Width Modulation)
void PWM_Init(void){
    // Configure P1.20 (PWM1.2) function as PWM output (bits 21:20 = 10)
    LPC_PINCON->PINSEL3 |= 0x02 << 8;
    // Enable power for PWM1 (bit 6)
    LPC_SC->PCONP |= 1 << 6;
    // Set prescaler to 0 (no division)
    LPC_PWM1->PR = 0;
    // Set timer in PWM mode (counter mode)
    LPC_PWM1->CTCR = 0;
    // Set PWM period (MR0 determines cycle frequency)
    LPC_PWM1->MR0 = 1000;
    // Set initial PWM duty cycle for channel 2 to 50%
    LPC_PWM1->MR2 = 500;
    // Enable shadow latch for MR0 and MR2
    LPC_PWM1->LER = 0x05;
    // Enable PWM output for channel 2 (bit 10)
    LPC_PWM1->PCR = 1 << 10;
    // Enable PWM counter and PWM mode (bits 3:0 = 1001)
    LPC_PWM1->TCR = 0x09;
    // Enable PWM1 interrupt in NVIC
    NVIC_EnableIRQ(PWM1_IRQn);
}

// Function to initialize keyboard GPIO pins
void Keyboard_Init(void){
    // Configure P0.0-P0.3 as GPIO (clear bits for pins 0-3 in PINSEL0)
    LPC_PINCON->PINSEL0 &= ~0x0FFF;
    // Set P0.0-P0.3 as input (clear bits 0-3 in FIODIR)
    LPC_GPIO0->FIODIR &= ~0x0F;
}

// Simple delay function for debouncing
void Delay(unsigned long count){
    for(unsigned long i = 0; i < count; i++);
}

// Function to read keyboard input with debouncing
unsigned char Read_Keyboard(void){
    // Check each of the 4 keyboard lines
    for(unsigned char i = 0; i < 4; i++){
        // If a key is pressed (pin is low)
        if(!(LPC_GPIO0->FIOPIN & (1 << i))){
            // Debounce delay
            Delay(500000);
            // Check if key is still pressed
            if(!(LPC_GPIO0->FIOPIN & (1 << i))){
                // Wait for key release
                while(!(LPC_GPIO0->FIOPIN & (1 << i)));
                // Debounce delay after release
                Delay(500000);
                // Return the key number (0-3)
                return i;
            }
        }
    }
    // Return 0xFF if no key pressed
    return 0xFF;
}

// Main program entry point
int main(void){
    unsigned char key;
    // Array of PWM values corresponding to each key
    const unsigned long pwm_values[] = {100, 250, 500, 750};

    // Initialize hardware peripherals
    PWM_Init();
    Keyboard_Init();

    // Main program loop
    while(1){
        // Read keyboard input
        key = Read_Keyboard();
        // If a valid key is pressed (0-3)
        if(key < 4){
            // Update PWM duty cycle based on key pressed
            LPC_PWM1->MR2 = pwm_values[key];
            // Enable latch for MR2 to update PWM output
            LPC_PWM1->LER |= 0x04;
        }
    }

    return 0;
}

// PWM1 interrupt handler
void PWM1_IRQHandler(void){
    // Clear interrupt flag for MR0 (bit 0)
    LPC_PWM1->IR |= 0x01;
}
