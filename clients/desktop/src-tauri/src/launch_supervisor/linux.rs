//! Only the dedicated guardian adopts and reaps game descendants.
use std::{io, process::Child};
extern "C" {
    fn prctl(option: i32, ...) -> i32;
    fn waitpid(pid: i32, status: *mut i32, options: i32) -> i32;
}
pub(super) struct Family;
impl Family {
    pub(super) fn new() -> io::Result<Self> {
        // PR_SET_CHILD_SUBREAPER, before the first game fork. This flag never
        // changes the companion and does not depend on process-group snapshots.
        if unsafe { prctl(36, 1usize, 0usize, 0usize, 0usize) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self)
    }
    pub(super) fn wait(&self, child: &mut Child) -> io::Result<()> {
        let root_pid = child.id();
        loop {
            let mut status = 0;
            // Blocking wait reaps both the wrapper and kernel-adopted orphans,
            // including children which changed their process group/session.
            let reaped = unsafe { waitpid(-1, &mut status, 0) };
            if reaped >= 0 {
                if reaped as u32 == root_pid {
                    #[cfg(test)]
                    super::tests::signal_wrapper_reaped();
                }
                continue;
            }
            let error = io::Error::last_os_error();
            match error.raw_os_error() {
                Some(4) => continue,       // EINTR
                Some(10) => return Ok(()), // ECHILD: no live/unreaped family remains.
                _ => return Err(error),
            }
        }
    }
}
