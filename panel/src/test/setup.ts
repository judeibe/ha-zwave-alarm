import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no modal <dialog>: model showModal/close as toggling `open`, which is all the panel relies on.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

window.scrollTo = () => {}; // the scroll lock restores the position; jsdom doesn't implement scrolling

afterEach(cleanup);
