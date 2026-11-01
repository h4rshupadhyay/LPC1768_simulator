ENTRY(Reset_Handler)
MEMORY {
 FLASH (rx) : ORIGIN = 0, LENGTH = 512K
 RAM (rwx) : ORIGIN = 0x10000000, LENGTH = 32K
}
SECTIONS {
 .vectors : { KEEP(*(.vectors)) } > FLASH
 .text : { *(.text*) *(.rodata*) } > FLASH
 .data : { *(.data*) } > RAM
 .bss (NOLOAD) : { *(.bss*) } > RAM
 /DISCARD/ : { *(.comment) *(.note*) *(.ARM.exidx*) *(.ARM.extab*) }
}
