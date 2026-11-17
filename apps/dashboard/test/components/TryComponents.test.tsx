import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerCard } from "@/components/AnswerCard";
import { RetryCountdown } from "@/components/RetryCountdown";
import { TryItForm } from "@/components/TryItForm";
import content from "@/content/try.json";
import de from "@/i18n/de.json";
import en from "@/i18n/en.json";
import { initialState, reduce, type Answer, type TryState } from "@/lib/try-state";

const base = (): TryState => initialState("kanzlei_mueller");
const form = (state: TryState, dispatch = vi.fn(), onSubmit = vi.fn()) =>
  render(
    <TryItForm
      locale="en"
      state={state}
      tenants={content.tenants}
      examples={content.examples}
      dispatch={dispatch}
      onSubmit={onSubmit}
      onCancel={vi.fn()}
    />,
  );

describe("TryItForm", () => {
  it("at load: no error, Ask disabled, German textarea on an English page", () => {
    const { container } = form(base());
    expect(screen.getByRole("button", { name: en["try.ask"] })).toBeDisabled();
    expect(container.querySelector("#try-problem")).toBeNull();
    expect(container.querySelector("textarea")).toHaveAttribute("lang", "de");
    for (const b of container.querySelectorAll("button[lang]"))
      expect(b).toHaveAttribute("lang", "de");
  });
  it("after typing and clearing the empty message is described by aria-describedby", () => {
    const s = reduce(reduce(base(), { type: "input", question: "x" }), {
      type: "input",
      question: "",
    });
    const { container } = form(s);
    expect(screen.getByText(en["try.invalid.empty"])).toBeInTheDocument();
    expect(container.querySelector("textarea")).toHaveAttribute(
      "aria-describedby",
      "try-count try-problem",
    );
  });
  it("at 500 characters the counter is marked full", () => {
    const s = reduce(base(), { type: "input", question: "x".repeat(600) });
    const { container } = form(s);
    expect(container.querySelector(".try-count--full")).toHaveTextContent("500 / 500");
  });
  it("does not validate on blur", () => {
    const { container } = form(base());
    fireEvent.blur(container.querySelector("textarea") as HTMLTextAreaElement);
    expect(container.querySelector("#try-problem")).toBeNull();
  });
  it("tenant labels and descriptions follow the page locale", () => {
    form(base());
    expect(screen.getByText(/Kanzlei Müller — law firm, labour law/)).toBeInTheDocument();
  });
  it("the limits line has no digits", () => {
    expect(de["try.limits"]).not.toMatch(/\d/);
    expect(en["try.limits"]).not.toMatch(/\d/);
  });
  it("an example fills tenant and question", () => {
    const dispatch = vi.fn();
    form(base(), dispatch);
    fireEvent.click(
      screen.getAllByRole("button", { name: /Schadenfreiheitsrabatt/ })[0] as HTMLElement,
    );
    expect(dispatch).toHaveBeenCalledWith({ type: "tenant", tenant: "versicherung_nord" });
  });
  it("while loading the textarea is read-only, Ask says asking and Cancel shows", () => {
    const s = reduce(reduce(base(), { type: "input", question: "Frage?" }), { type: "submit" });
    const { container } = form(s);
    expect(container.querySelector("textarea")).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: en["try.asking"] })).toBeDisabled();
    expect(screen.getByRole("button", { name: en["try.cancel"] })).toBeInTheDocument();
  });
});

const ANSWER: Answer = {
  answer: "Vier Wochen.",
  citations: ["§ 622 BGB"],
  refused: true,
  model: "qwen",
  chunks: [
    {
      chunk_id: "a",
      doc_id: "d1",
      tenant_id: "kanzlei_mueller",
      text: "Text eins",
      score: 0.82,
      rank: 1,
      used_in_prompt: true,
    },
    {
      chunk_id: "b",
      doc_id: "d2",
      tenant_id: "shared_public",
      text: "Text zwei",
      score: 0.41,
      rank: 2,
      used_in_prompt: false,
    },
    {
      chunk_id: "c",
      doc_id: "d3",
      tenant_id: null,
      text: "Text drei",
      score: 0.3,
      rank: 3,
      used_in_prompt: null,
    },
  ],
};

describe("AnswerCard", () => {
  it("shows the refused badge, German text, citations and the not-in-prompt note only for false", () => {
    const { container } = render(
      <AnswerCard locale="en" answer={ANSWER} elapsedS={12} tenant="kanzlei_mueller" />,
    );
    expect(screen.getByText(en["try.refused"])).toBeInTheDocument();
    expect(container.querySelector("p.case-text")).toHaveAttribute("lang", "de");
    expect(screen.getByText("§ 622 BGB")).toHaveAttribute("lang", "de");
    expect(screen.getAllByText(new RegExp(en["try.not_in_prompt"]))).toHaveLength(1);
    expect(screen.getByText(/12 s/)).toBeInTheDocument();
  });
  it("without a refusal there is no badge", () => {
    render(
      <AnswerCard
        locale="de"
        answer={{ ...ANSWER, refused: false }}
        elapsedS={3}
        tenant="kanzlei_mueller"
      />,
    );
    expect(screen.queryByText(de["try.refused"])).toBeNull();
  });
});

describe("RetryCountdown", () => {
  it("counts down visibly while the announced text stays fixed, then announces the retry", () => {
    const { container, rerender } = render(
      <RetryCountdown locale="en" messageKey="try.error.busy" initialS={5} remainingS={3} />,
    );
    expect(container.querySelector("[aria-hidden]")).toHaveTextContent("3 s");
    expect(container.querySelector(".sr-only")).toHaveTextContent("5 s");
    rerender(
      <RetryCountdown locale="en" messageKey="try.error.busy" initialS={5} remainingS={0} />,
    );
    expect(container.querySelector(".sr-only")).toHaveTextContent(en["try.retry"]);
    expect(container.firstElementChild).toHaveAttribute("role", "alert");
  });
});

describe("try.* strings", () => {
  it("exist in de and en with the same keys", () => {
    const keys = (d: Record<string, string>) =>
      Object.keys(d)
        .filter((k) => k.startsWith("try."))
        .sort();
    expect(keys(de)).toEqual(keys(en));
  });
});
