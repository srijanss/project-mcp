use std::fmt;

pub struct Widget {
    pub name: String,
}

pub trait Describe {
    fn describe(&self) -> String;
}

impl Describe for Widget {
    fn describe(&self) -> String {
        self.name.clone()
    }
}

impl fmt::Display for Widget {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}", self.name)
    }
}
