/* @license magnet:?xt=urn:btih:d3d9a9a6595521f9666a5e94cc830dab83b65699&dn=expat.txt MIT
 * Copyright (c) 2026 Security Ops contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */
"use strict";
(() => {
  let busy = false;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.body.classList.contains("reduced-motion") || document.querySelector("#motion-toggle")?.checked;
  const sameOrigin = value => {
    const url = new URL(value, location.href);
    if (url.origin !== location.origin || url.username || url.password) throw new Error("Foreign URL rejected");
    return url;
  };
  function syncPicks() {
    const table = document.querySelector("#practice-table");
    if (!table || table.dataset.game !== "keno") return;
    const inputs = [...table.querySelectorAll(".keno-inputs input")];
    if (!inputs.length) return;
    const selected = new Set(inputs.map(input => Number(input.value)));
    table.querySelectorAll("[data-pick]").forEach(button => {
      button.setAttribute("aria-pressed", String(selected.has(Number(button.dataset.pick))));
    });
  }
  function checkedFragment(html) {
    // Only our same-origin response template is accepted. Never execute scripts
    // from a response or assign an HTML string to an existing DOM element.
    if (typeof html !== "string" || html.length > 180000) throw new Error("Invalid fragment");
    const doc = new DOMParser().parseFromString(html, "text/html");
    const next = doc.querySelector("section#practice-table");
    if (!next || doc.querySelectorAll("#practice-table").length !== 1) throw new Error("Invalid table response");
    if (next.querySelector("script,style,iframe,object,embed,link,svg,math,base,meta")) throw new Error("Unexpected active content");
    for (const element of [next, ...next.querySelectorAll("*")]) {
      for (const attribute of element.attributes) {
        if (/^on/i.test(attribute.name) || attribute.name === "style" || attribute.name === "srcdoc") throw new Error("Unexpected active attribute");
        if (["href", "action", "formaction", "src"].includes(attribute.name)) sameOrigin(attribute.value);
      }
    }
    return document.importNode(next, true);
  }
  async function animateResult(table) {
    if (reduced() || typeof Element.prototype.animate !== "function") return;
    const animations = [];
    const ring = table.querySelector(".wheel-ring");
    if (ring && /^\d+$/.test(table.dataset.pocketIndex || "")) {
      const index = Number(table.dataset.pocketIndex);
      if (index < 37) animations.push(ring.animate([{transform:"rotate(0deg)"}, {transform:`rotate(${1080-index*360/37}deg)`}], {duration:1000, easing:"cubic-bezier(.15,.65,.25,1)",fill:"forwards"}));
    }
    table.querySelectorAll(".playing-card").forEach((card,index) => {
      animations.push(card.animate([{opacity:0,transform:"translateY(-12px) rotateY(80deg)"},{opacity:1,transform:"none"}],{duration:240,delay:Math.min(index,5)*65,fill:"both"}));
    });
    table.querySelectorAll(".slot-reel span").forEach((symbol,index) => {
      animations.push(symbol.animate([{transform:"translateY(-90px)",opacity:0},{transform:"translateY(0)",opacity:1}],{duration:450+index*200,easing:"cubic-bezier(.1,.7,.3,1)",fill:"both"}));
    });
    table.querySelectorAll(".die").forEach(die => {
      animations.push(die.animate([{transform:"rotate(-90deg) scale(.7)"},{transform:"none"}],{duration:430,easing:"ease-out"}));
    });
    const ball=table.querySelector(".plinko-ball"), board=table.querySelector(".plinko-board");
    if (ball && board && /^[01]{8}$/.test(table.dataset.steps || "")) {
      let position=0;
      const frames=[{transform:"translate(0,0)",offset:0}];
      [...table.dataset.steps].forEach((bit,index) => {
        position += bit === "1" ? 1 : -1;
        frames.push({transform:`translate(${position*board.clientWidth/18}px,${(index+1)*(board.querySelector(".plinko-bins").offsetTop+7)/8}px)`,offset:(index+1)/8});
      });
      animations.push(ball.animate(frames,{duration:950,easing:"linear",fill:"forwards"}));
    }
    table.querySelectorAll(".keno-drawn,.keno-hit").forEach((cell,index) => {
      animations.push(cell.animate([{opacity:.3,transform:"scale(.8)"},{opacity:1,transform:"scale(1)"}],{duration:180,delay:index*45,fill:"both"}));
    });
    await Promise.all(animations.map(animation => animation.finished.catch(() => {})));
  }
  document.addEventListener("input", event => {
    if (event.target.matches(".keno-inputs input")) syncPicks();
  });
  document.addEventListener("click", event => {
    const button = event.target.closest("button[data-pick]");
    if (!button || button.disabled || busy) return;
    const inputs=[...document.querySelectorAll("#practice-table .keno-inputs input")];
    const chosen=inputs.find(input => Number(input.value)===Number(button.dataset.pick));
    if (chosen) chosen.value="";
    else { const empty=inputs.find(input => !input.value); if (empty) empty.value=button.dataset.pick; }
    syncPicks();
  });
  document.addEventListener("submit", async event => {
    const form=event.target;
    if (!form.matches("form[data-live-form]")) return;
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const message=document.querySelector("#table-message"), table=document.querySelector("#practice-table");
    const inputs=[...form.querySelectorAll(".keno-inputs input")];
    if (inputs.length && new Set(inputs.map(input => Number(input.value))).size!==5) {
      inputs[0].setCustomValidity(document.querySelector(".keno-inputs").closest("fieldset").querySelector("legend").textContent);
      inputs[0].reportValidity(); inputs[0].setCustomValidity(""); return;
    }
    const payload=new URLSearchParams(new FormData(form));
    if (event.submitter?.name) payload.set(event.submitter.name,event.submitter.value);
    const url=sameOrigin(form.action);
    busy=true; table.setAttribute("aria-busy","true"); message.textContent=message.dataset.pending;
    const controls=[...form.querySelectorAll("button,input,select")];
    controls.forEach(control => { control.disabled=true; });
    const controller=new AbortController(), timer=setTimeout(() => controller.abort(),20000);
    try {
      const response=await fetch(url,{method:"POST",credentials:"same-origin",redirect:"error",headers:{"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},body:payload,signal:controller.signal});
      if (!response.ok || !response.headers.get("content-type")?.startsWith("application/json")) throw new Error("Request was not accepted");
      const data=await response.json();
      const nextURL=sameOrigin(data.url);
      if (!/^\/play\/[a-z]+\/[a-f0-9]{32}$/.test(nextURL.pathname)) throw new Error("Unexpected round URL");
      const next=checkedFragment(data.html);
      next.setAttribute("aria-busy","true");
      table.replaceWith(next);
      history.replaceState(null,"",nextURL.pathname);
      await animateResult(next);
      message.textContent="";
      const status=next.querySelector(".round-status");
      if (status) {status.tabIndex=-1;status.focus({preventScroll:true});}
      syncPicks();
    } catch (_) {
      // Aborting a request does not undo its server transaction. Never retry a
      // bet automatically; saved rounds can be recovered from the collection.
      message.textContent=message.dataset.failed;
    } finally { clearTimeout(timer);busy=false;document.querySelector("#practice-table")?.removeAttribute("aria-busy"); }
  });
  syncPicks();
})();
/* @license-end */
