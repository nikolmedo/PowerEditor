import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { NumberField } from "../src/ui/primitives";

function Harness({ onChange }: { onChange: (value: number) => void }) {
  const [value, setValue] = useState(64);
  return (
    <NumberField
      label="Font size"
      value={value}
      min={16}
      max={160}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

describe("NumberField", () => {
  it("keeps partial input while typing and clamps it when the field is left", async () => {
    const changes = vi.fn();
    render(<Harness onChange={changes} />);
    const input = screen.getByLabelText("Font size");

    await userEvent.clear(input);
    await userEvent.type(input, "1");
    expect(input).toHaveProperty("value", "1");
    expect(changes).not.toHaveBeenCalled();

    await userEvent.type(input, "20");
    expect(changes).toHaveBeenLastCalledWith(120);
    await userEvent.clear(input);
    await userEvent.type(input, "9{enter}");
    expect(changes).toHaveBeenLastCalledWith(16);
    expect(input).toHaveProperty("value", "16");
  });

  it("falls back to the current value when the entry is not a number", async () => {
    const changes = vi.fn();
    render(<Harness onChange={changes} />);
    const input = screen.getByLabelText("Font size");

    await userEvent.clear(input);
    await userEvent.tab();
    expect(changes).not.toHaveBeenCalled();
    expect(input).toHaveProperty("value", "64");
  });
});
