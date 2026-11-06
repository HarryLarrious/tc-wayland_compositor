# Program entry: the runner sets sp to the top of RAM and pc to 0.
    .section .text.start
    .globl _start
_start:
    call main
    li a7, 93       # exit(main's return value)
    ecall
1:  j 1b
