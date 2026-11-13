//! Kernel inheritance is established in a disposable guardian before game spawn.
use std::{ffi::c_void, io, process::Child, thread, time::Duration};
type Handle = *mut c_void;
#[repr(C)]
#[derive(Default)]
struct Accounting {
    user: i64,
    kernel: i64,
    period_user: i64,
    period_kernel: i64,
    faults: u32,
    total: u32,
    active: u32,
    terminated: u32,
}
#[repr(C)]
#[derive(Default)]
struct BasicLimits {
    process_time: i64,
    job_time: i64,
    flags: u32,
    min_working: usize,
    max_working: usize,
    active: u32,
    affinity: usize,
    priority: u32,
    scheduling: u32,
}
#[repr(C)]
#[derive(Default)]
struct ExtendedLimits {
    basic: BasicLimits,
    io: [u64; 6],
    memory: [usize; 4],
}
#[link(name = "kernel32")]
extern "system" {
    fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> Handle;
    fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
    fn SetInformationJobObject(job: Handle, class: i32, buffer: *const c_void, length: u32) -> i32;
    fn QueryInformationJobObject(
        job: Handle,
        class: i32,
        buffer: *mut c_void,
        length: u32,
        returned: *mut u32,
    ) -> i32;
    fn GetCurrentProcess() -> Handle;
    fn CloseHandle(handle: Handle) -> i32;
}
struct Job(Handle);
impl Job {
    fn join(allow_breakaway: bool) -> io::Result<Self> {
        // NULL security attributes: the handle is not inheritable by game children.
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(io::Error::last_os_error());
        }
        let job = Self(handle);
        if allow_breakaway {
            let limits = ExtendedLimits {
                basic: BasicLimits {
                    flags: 0x800,
                    ..Default::default()
                },
                ..Default::default()
            };
            if unsafe {
                SetInformationJobObject(
                    handle,
                    9,
                    &limits as *const _ as *const c_void,
                    std::mem::size_of::<ExtendedLimits>() as u32,
                )
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
        }
        if unsafe { AssignProcessToJobObject(handle, GetCurrentProcess()) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(job)
    }
    fn active(&self) -> io::Result<u32> {
        let mut info = Accounting::default();
        if unsafe {
            QueryInformationJobObject(
                self.0,
                1,
                &mut info as *mut _ as *mut c_void,
                std::mem::size_of::<Accounting>() as u32,
                std::ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(info.active)
    }
}
impl Drop for Job {
    fn drop(&mut self) {
        // No KILL_ON_JOB_CLOSE, TerminateJobObject, resource or UI restrictions.
        unsafe {
            CloseHandle(self.0);
        }
    }
}
pub(super) struct Family {
    outer: Job,
    _inner: Job,
}
impl Family {
    pub(super) fn new() -> io::Result<Self> {
        let outer = Job::join(false)?;
        // An explicit breakaway can leave this inner job while remaining in the
        // outer tracking job. A default immediate job would reject its creation.
        let inner = Job::join(true)?;
        Ok(Self {
            outer,
            _inner: inner,
        })
    }
    pub(super) fn wait(&self, child: &mut Child) -> io::Result<()> {
        loop {
            if child.try_wait()?.is_some() {
                #[cfg(test)]
                super::tests::signal_wrapper_reaped();
            }
            if self.outer.active()? <= 1 {
                child.wait()?;
                return Ok(());
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
}
