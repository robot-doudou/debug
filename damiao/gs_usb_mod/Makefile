obj-m := gs_usb.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

install:
	install -d $(DESTDIR)/lib/modules/$(shell uname -r)/extra
	install -m 0644 gs_usb.ko $(DESTDIR)/lib/modules/$(shell uname -r)/extra/
	depmod -a

uninstall:
	rm -f /lib/modules/$(shell uname -r)/extra/gs_usb.ko
	depmod -a

.PHONY: all clean install uninstall
