import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorState, InsufficientHistory, StatTile } from "../components/Primitives";

describe("StatTile", () => {
  it("renders label, value and sub", () => {
    render(<StatTile label="Current value" value="$5,000.00" sub="Invested $5,005.07" />);
    expect(screen.getByText("Current value")).toBeInTheDocument();
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(screen.getByText("Invested $5,005.07")).toBeInTheDocument();
  });
  it("colors positive returns green", () => {
    render(<StatTile label="TWR" value="+1.00%" signed={0.01} />);
    expect(screen.getByText("+1.00%").className).toContain("pos");
  });
});

describe("InsufficientHistory", () => {
  it("explains the observation requirement in the tooltip", () => {
    render(<InsufficientHistory label="Beta" needed={10} have={3} />);
    const el = screen.getByText("insufficient history");
    expect(el).toHaveAttribute("title", expect.stringContaining("10"));
  });
});

describe("ErrorState", () => {
  it("shows the message", () => {
    render(<ErrorState message="Market data provider error" />);
    expect(screen.getByText(/Market data provider error/)).toBeInTheDocument();
  });
});
