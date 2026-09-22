function formatLabel(label) {
  return label.toUpperCase();
}

class Widget {
  constructor(label) {
    this.label = label;
  }

  render() {
    return formatLabel(this.label);
  }
}

module.exports = { Widget, formatLabel };
