#!/usr/bin/env python3
"""Check the actual early firmware function against fake disks and mounts."""
import os
import re
from pathlib import Path
import subprocess
import tempfile

TOP=Path(__file__).resolve().parents[2]
source=(TOP/'boot/init').read_text()
function=source[source.index('early_card_firmware() {'):source.index('\nearly_device_firmware() {')]
assert '-o ro,noload,noatime' in function
# wcn_bsp's firmware has to be in place before the module is loaded. The guard
# started as a direct test of the module name; it became a case statement when
# st7123 (and later axs15205) needed the same firmware before probe, so read the
# module pass and accept either form, as long as wcn_bsp is covered before insmod.
start=source.index('while read module; do')
loop=source[start:source.index('done < /etc/module-order', start)]
pass_at=loop.index('insmod "/linux-modules/$module"')
arms=[a for a in ('[ "$module" = wcn_bsp.ko ] && early_device_firmware',
                  'st7123.ko|wcn_bsp.ko) early_device_firmware ;;',
                  'st7123.ko|axs15205.ko|wcn_bsp.ko) early_device_firmware ;;')
      if a in loop]
assert len(arms)==1,'boot/init: expected one guard that runs early_device_firmware for wcn_bsp, found %d' % len(arms)
assert loop.index(arms[0]) < pass_at,'boot/init: wcn_bsp firmware is read after the module pass insmods it'
with tempfile.TemporaryDirectory(prefix='e5-early-fw-') as directory:
    root=Path(directory)
    for path in ['sys/mmcblk0','sys/mmcblk1','dev','card/lib/firmware','card/etc/e5','card/sbin','bin','firmware']:
        (root/path).mkdir(parents=True)
    for name in ['mmcblk0p1','mmcblk1p1']:(root/'dev'/name).touch()
    (root/'card/etc/e5/sd-root').touch()
    (root/'card/lib/firmware/wcnmodem.bin').write_text('this-device-firmware')
    (root/'card/sbin/init').write_text('#!/bin/sh\n');(root/'card/sbin/init').chmod(0o755)
    def command(name,body):
        path=root/'bin'/name;path.write_text('#!/bin/sh\n'+body);path.chmod(0o755)
    command('mdev','exit 0\n')
    command('sleep','exit 0\n')
    command('mount','echo "$*" >> "$TEST_LOG"\n[ "${5##*/}" = mmcblk1p1 ] || exit 1\ncp -R "$TEST_CARD/." "$6/"\n')
    command('umount','rm -rf "$1"; mkdir -p "$1"\n')
    # Replace the original paths once. On Linux the temporary directory itself
    # starts with /tmp/e5-early-fw, so chained replace() corrupts inserted paths.
    paths={'/sys/class/block':str(root/'sys'),'/dev/':str(root/'dev')+'/',
           '/tmp/e5-early-fw':str(root/'mounted')}
    actual=re.sub('|'.join(re.escape(p) for p in paths),lambda m:paths[m.group()],function)
    actual=actual.replace('[ -b "$part" ]','[ -f "$part" ]')
    actual=actual.replace('mkdir -p /lib/firmware','mkdir -p '+str(root/'firmware'))
    actual=actual.replace(' /lib/firmware/;', ' '+str(root/'firmware')+'/;').replace('ls /lib/firmware','ls '+str(root/'firmware'))
    script=root/'test.sh';script.write_text('set -eu\nlog() { echo "$*"; }\n'+actual+'\nearly_card_firmware mmcblk0\n')
    env={**os.environ,'PATH':str(root/'bin')+':'+os.environ['PATH'],'TEST_LOG':str(root/'mounts'),'TEST_CARD':str(root/'card')}
    result=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode==0,(result.stdout,result.stderr)
    assert (root/'firmware/wcnmodem.bin').read_text()=='this-device-firmware'
    log=(root/'mounts').read_text();assert 'ro,noload,noatime' in log and 'mmcblk0p1' not in log
    (root/'card/lib/firmware/wcnmodem.bin').unlink()
    result=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode!=0,'missing card firmware was reported as loaded'
print('Early SD firmware checks passed without mounting userdata')
