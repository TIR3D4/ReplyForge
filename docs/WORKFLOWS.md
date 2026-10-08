# Configurable support workflows

Select a YAML playbook with BUSINESS_CONFIG. The default is config/business.yaml; examples/azadbird.yaml demonstrates a Persian VPN support workflow.

A playbook defines: brand, locale, welcome, handoff_text, resolution_text, menu and workflows.

## Menu

Each menu item has a label and either action: human or action: flow:NAME, where NAME exists in workflows. The server generates callback_data using a random nonce and numeric index; authors must **never** put executable commands in actions.

## Workflows

Every workflow has a start state and a states mapping. State forms:

- input: text — ask for free text, store a redacted answer under field, transition to next.
- input: choice — show inline options with value and optional next; supports free text inference when AI is configured.
- input: photo — require a Telegram photo or image document and store the opaque file_id for the human operator.
- input: subscription — require a subscription URL; match HMAC to a pre-registered provider reference; lookup read-only account details. On unknown/unavailable, hand off.
- input: question — search approved FAQ after receiving free text.
- type: knowledge — reply with a matched, approved answer or hand off.
- type: handoff — open a human ticket, stop AI.
- type: complete — finish and allow returning to home.

All transitions must lead to a defined state. The playbook validator rejects undefined workflow names, destinations and unsupported state types.

## Example

~~~yaml
brand: Example Shop
locale: en
welcome: "Welcome. What can we help with?"
handoff_text: "A person will review your question."
resolution_text: "Thanks!"
menu:
  - {label: "Order", action: "flow:orders"}
  - {label: "Human", action: "human"}
workflows:
  orders:
    start: reference
    states:
      reference:
        prompt: "What's your order reference?"
        input: text
        field: order_reference
        next: human
      human: {type: handoff}
~~~

## Authoring guidelines

Ask one question at a time. Avoid demanding passwords or excessive personal information. Financial workflows should never auto-approve bank transfers using screenshots or SMS. Test every branch with real Telegram clients before enabling self-serve workflows on your business account.

V1 changes to playbook YAML require restarting API and worker. The operator panel edits approved FAQ answers and manually associates subscription links.
