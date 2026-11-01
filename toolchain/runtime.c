/* SPDX-License-Identifier: MIT. Freestanding memory routines, no host libc. */
#include <stddef.h>
__attribute__((weak)) void *memcpy(void *dst, const void *src, size_t n) {
  unsigned char *d = dst; const unsigned char *s = src;
  for (size_t i=0; i<n; i++) d[i]=s[i];
  return dst;
}
__attribute__((weak)) void *memmove(void *dst, const void *src, size_t n) {
  unsigned char *d = dst; const unsigned char *s = src;
  if (d<s) return memcpy(dst,src,n);
  while(n) { n--; d[n]=s[n]; }
  return dst;
}
__attribute__((weak)) void *memset(void *dst, int c, size_t n) {
  unsigned char *d = dst;
  for(size_t i=0;i<n;i++) d[i]=(unsigned char)c;
  return dst;
}
void __aeabi_memcpy(void *d,const void *s,size_t n) { (void)memcpy(d,s,n); }
void __aeabi_memcpy4(void *d,const void *s,size_t n) { (void)memcpy(d,s,n); }
void __aeabi_memcpy8(void *d,const void *s,size_t n) { (void)memcpy(d,s,n); }
void __aeabi_memset(void *d,size_t n,int c) { (void)memset(d,c,n); }
void __aeabi_memclr(void *d,size_t n) { (void)memset(d,0,n); }
void __aeabi_memclr4(void *d,size_t n) { (void)memset(d,0,n); }
void __aeabi_memclr8(void *d,size_t n) { (void)memset(d,0,n); }
