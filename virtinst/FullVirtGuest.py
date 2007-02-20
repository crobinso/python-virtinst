#!/usr/bin/python -tt
#
# Fullly virtualized guest support
#
# Copyright 2006-2007  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This software may be freely redistributed under the terms of the GNU
# general public license.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import os
import libvirt
import Guest
import util
import DistroManager

class FullVirtGuest(Guest.XenGuest):
    OS_TYPES = { "Linux" : { "Red Hat Enterprise Linux AS 2.1/3" : { "acpi" : True, "apic": True }, \
                             "Red Hat Enterprise Linux 4" : { "acpi" : True, "apic": True }, \
                             "Red Hat Enterprise Linux 5" : { "acpi" : True, "apic": True }, \
                             "Fedora Core 4-6" : { "acpi" : True, "apic": True }, \
                             "Suse Linux Enterprise Server" : { "acpi" : True, "apic": True }, \
                             "Other Linux 2.6 kernel" : { "acpi" : True, "apic": True } }, \
                 "Microsoft Windows" : { "Windows 2000" : { "acpi": False, "apic" : False }, \
                                         "Windows XP" : { "acpi": True, "apic" : True }, \
                                         "Windows Server 2003" : { "acpi": True, "apic" : True }, \
                                         "Windows Vista" : { "acpi": True, "apic" : True } }, \
                 "Novell Netware" : { "Netware 4" : { "acpi": True, "apic": True }, \
                                      "Netware 5" : { "acpi": True, "apic": True }, \
                                      "Netware 6" : { "acpi": True, "apic": True } }, \
                 "Sun Solaris" : { "Solaris 10" : { "acpi": True, "apic": True }, \
                                   "Solaris 9" : { "acpi": True, "apic": True } }, \
                 "Other" : { "MS-DOS" : { "acpi": False, "apic" : False }, \
                             "Free BSD" : { "acpi": True, "apic" : True }, \
                             "Other" : { "acpi": True, "apic" : True } } }

    def __init__(self, type=None, arch=None, connection=None, hypervisorURI=None, emulator=None):
        Guest.Guest.__init__(self, type=type, connection=connection, hypervisorURI=hypervisorURI)
        self.disknode = "hd"
        self.features = { "acpi": None, "pae": util.is_pae_capable(), "apic": None }
        self.arch = arch
        if emulator is None:
            if self.type == "xen":
                if os.uname()[4] in ("x86_64"):
                    emulator = "/usr/lib64/xen/bin/qemu-dm"
                else:
                    emulator = "/usr/lib/xen/bin/qemu-dm"
        self.emulator = emulator
        if self.type == "xen":
            self.loader = "/usr/lib/xen/boot/hvmloader"
        else:
            self.loader = None
        self._os_type = None
        self._os_variant = None

    def get_os_type(self):
        return self._os_type
    def set_os_type(self, val):
        if FullVirtGuest.OS_TYPES.has_key(val):
            self._os_type = val
        else:
            raise RuntimeError, "OS type %s does not exist in our dictionary" % val
    os_type = property(get_os_type, set_os_type)

    def get_os_variant(self):
        return self._os_variant
    def set_os_variant(self, val):
        if FullVirtGuest.OS_TYPES[self._os_type].has_key(val):
            self._os_variant = val
        else:
            raise RuntimeError, "OS variant %s does not exist in our dictionary for OS type %s" % (val, os_type)
    os_variant = property(get_os_variant, set_os_variant)

    def set_os_type_parameters(self, os_type, os_variant):
        # explicitly disabling apic and acpi will override OS_TYPES values
        acpi = FullVirtGuest.OS_TYPES[os_type][os_variant]["acpi"]
        apic = FullVirtGuest.OS_TYPES[os_type][os_variant]["apic"]
        if self.features["acpi"] == None:
            self.features["acpi"] = acpi
        if self.features["apic"] == None:
            self.features["apic"] = apic

    def _get_features_xml(self):
        ret = ""
        for (k, v) in self.features.items():
            if v:
                ret += "<%s/>" %(k,)
        return ret

    def _get_loader_xml(self):
        if self.loader is None:
            return ""

        return """    <loader>%(loader)s</loader>""" % { "loader": self.loader }

    def _get_os_xml(self, bootdev, install=True):
        if self.arch is None:
            arch = ""
        else:
            arch = " arch='" + self.arch + "'"

        if self.kernel is None or install == False:
            return """<os>
    <type%(arch)s>hvm</type>
%(loader)s
    <boot dev='%(bootdev)s'/>
  </os>
  <features>
    %(features)s
  </features>""" % \
    { "bootdev": bootdev, \
      "arch": arch, \
      "loader": self._get_loader_xml(), \
      "features": self._get_features_xml() }
        else:
            return """<os>
    <type%(arch)s>hvm</type>
    <kernel>%(kernel)s</kernel>
    <initrd>%(initrd)s</initrd>
    <cmdline>%(extra)s</cmdline>
    <features>
      %(features)s
    </features>
  </os>""" % \
    { "kernel": self.kernel, \
      "initrd": self.initrd, \
      "extra": self.extraargs, \
      "arch": arch, \
      "features": self._get_features_xml() }

    def _get_install_xml(self):
        return self._get_os_xml("cdrom", True)

    def _get_runtime_xml(self):
        return self._get_os_xml("hd", False)

    def _get_device_xml(self, install = True):
        if self.emulator is None:
            return """    <console device='pty'/>
""" + Guest.Guest._get_device_xml(self, install)
        else:
            return ("""    <emulator>%(emulator)s</emulator>
    <console device='pty'/>
""" % { "emulator": self.emulator }) + \
        Guest.Guest._get_device_xml(self, install)

    def validate_parms(self):
        if not self.location:
            raise RuntimeError, "A CD must be specified to boot from"
        self.set_os_type_parameters(self.os_type, self.os_variant)
        Guest.Guest.validate_parms(self)

    def _prepare_install_location(self, meter):
        cdrom = None
        tmpfiles = []
        self.kernel = None
        self.initrd = None
        if self.location.startswith("/"):
            # Huzzah, a local file/device
            cdrom = self.location
        else:
            # Hmm, qemu ought to be able to boot off a kernel/initrd but
            # for some reason it often fails, hence disabled here..
            if self.type == "qemuXXX":
                # QEMU can go straight off a kernel/initrd
                if self.boot is not None:
                    # Got a local kernel/initrd already
                    self.kernel = self.boot["kernel"]
                    self.initrd = self.boot["initrd"]
                else:
                    (kernelfn,initrdfn,args) = DistroManager.acquireKernel(self.location, meter, scratchdir=self.scratchdir)
                    self.kernel = kernelfn
                    self.initrd = initrdfn
                    if self.extraargs is not None:
                        self.extraargs = self.extraargs + " " + args
                    else:
                        self.extraargs = args
                    tmpfiles.append(kernelfn)
                    tmpfiles.append(initrdfn)
            else:
                # Xen needs a boot.iso if its a http://, ftp://, or nfs:/ url
                cdrom = DistroManager.acquireBootDisk(self.location, meter, scratchdir=self.scratchdir)
                tmpfiles.append(cdrom)

        if cdrom is not None:
            self.disks.append(Guest.VirtualDisk(cdrom, device=Guest.VirtualDisk.DEVICE_CDROM, readOnly=True, transient=True))

        return tmpfiles