import { useEffect, useState } from "react";
import { useApp } from "../state/store";
import { cancelBuild, startBuild } from "../net/client";
import { demoPrompts } from "../spec/fixtures";
import { Icon } from "../ui/common";

/** C02 PromptBar: Enter sends build.start; Stop (build.cancel) while running. */
export function PromptBar(props: { docked?: boolean; autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const ready = useApp((s) => s.conn === "open" || s.conn === "resyncing");
  const helloSeen = useApp((s) => s.hello !== null);
  const pending = useApp((s) => s.pendingStart !== null);
  const status = useApp((s) => s.build?.status);
  const running = status === "running" || status === "awaiting_input";
  const maxChars = useApp((s) => s.hello?.limits?.max_prompt_chars ?? 2000);
  const disabled = !helloSeen || !ready;

  const submit = () => {
    if (disabled || pending || !text.trim()) return;
    startBuild(text.slice(0, maxChars));
    setText("");
  };

  return (
    <form
      className={`promptbar ${props.docked ? "docked" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        className="prompt-input"
        value={text}
        maxLength={maxChars}
        autoFocus={props.autoFocus}
        placeholder={disabled ? "Waiting for the server" : props.docked ? "Describe another device" : "Describe the device you want"}
        aria-label="Prompt"
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
      />
      {running && !text ? (
        <button type="button" className="btn stop" onClick={cancelBuild} title="Stop the build">
          <Icon name="stop" /> Stop
        </button>
      ) : (
        <button type="submit" className="btn primary" disabled={disabled || pending || !text.trim()}>
          {pending ? <span className="spinner light" aria-label="Sending" /> : <Icon name="send" />}
          Build
        </button>
      )}
    </form>
  );
}

/** C03 ExampleChips: one chip per demo prompt from the stream fixtures. */
export function ExampleChips() {
  const [items, setItems] = useState<{ fixture: string; prompt: string }[]>([]);
  const helloSeen = useApp((s) => s.hello !== null);
  useEffect(() => {
    let live = true;
    void demoPrompts().then((p) => {
      if (live) setItems(p);
    });
    return () => {
      live = false;
    };
  }, []);
  return (
    <div className="example-chips" aria-label="Examples">
      {items.map((it) => (
        <button key={it.fixture} type="button" className="example-chip" disabled={!helloSeen} onClick={() => startBuild(it.prompt)}>
          {it.prompt}
        </button>
      ))}
    </div>
  );
}
