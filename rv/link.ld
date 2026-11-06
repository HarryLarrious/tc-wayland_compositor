/* One flat image from address 0: code, read-only data, data, then bss.
   The runner (src/rv.tc) loads it into a 40,000-byte RAM and starts at 0
   with sp at the top. */
ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { *(.text.start) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) }
    .data : { *(.data .data.* .sdata .sdata.*) }
    .bss : { *(.bss .bss.* .sbss .sbss.* COMMON) }
    __end = .;
    /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note*) *(.eh_frame*) }
}
