"""PoC skill: solution proposal, PoC plan and interactive demo site (gpt-4o)."""
import re

from core import llm

SYS = ("You are a senior Microsoft Azure solutions architect. Write formal, "
       "accurate Markdown documents in English. Output the document body "
       "directly, starting with a level-1 heading. Mark uncertain items [TBC].")

P_PROP = ("Based on the customer research and industry context, write a 'Solution "
          "Proposal' for the customer scenario, covering: requirements and goals; "
          "overall architecture (draw it as a mermaid code block); an Azure "
          "service mapping table (need -> Azure service -> rationale); a focused "
          "section on why Azure Container Apps dynamic sessions replaces "
          "traditional VMs as the PoC/execution sandbox (comparison table: "
          "startup speed / isolation / ops / billing); implementation roadmap "
          "(PoC -> pilot -> rollout); risk and compliance mitigations; "
          "indicative cost notes.\nCustomer: {customer}\nIndustry: {industry}\n"
          "Scenario: {scenario}\nCustomer research summary: {cust_sum}")

P_POC = ("Write a 'PoC Implementation Plan'. The PoC runs inside an Azure "
         "Container Apps dynamic sessions sandbox (the very environment hosting "
         "this document), covering: PoC goals and measurable success criteria; "
         "scope and non-goals; PoC architecture (mermaid code block); environment "
         "notes (the sandbox is an XFCE desktop container with Chrome / FileZilla "
         "/ CLI tools, allocated in seconds from a session pool and auto-destroyed "
         "when idle); step-by-step execution plan with copy-pasteable az CLI "
         "examples — any step that provisions additional Azure services MUST be "
         "tagged [REQUIRES USER AUTHORIZATION]; validation cases and acceptance "
         "checklist; a two-week timeline; exit and resource cleanup.\n"
         "Customer: {customer}\nScenario: {scenario}\nProposal summary: {prop_sum}")

SYS_DEMO = ("You are a senior front-end engineer. Output one complete single-file "
            "HTML page (inline CSS/JS, CDNs allowed) that serves as a customer-"
            "facing PoC demo site: simulate the core screens and interactions of "
            "the target solution with realistic mock data, modern look (dark "
            "sidebar + card layout), all copy in English, and a top banner "
            "reading 'PoC Demo - Simulated Data'. Charts may use the Chart.js "
            "CDN. Output HTML code only, no explanations.")

P_DEMO = ("Customer: {customer} (industry: {industry})\nScenario: {scenario}\n"
          "Proposal highlights: {prop_sum}\nGenerate the demo site with: one "
          "overview dashboard (3-4 KPI cards + 1-2 charts); one core workflow "
          "demo area (e.g. an AI analysis/generation interaction where clicking "
          "a button reveals pre-baked mock results); one 'About this PoC' "
          "section (note it runs in an Azure Container Apps dynamic sessions "
          "sandbox).")


def solution_proposal(customer: str, industry: str, scenario: str,
                      cust_sum: str) -> str:
    return llm(SYS, P_PROP.format(customer=customer, industry=industry,
                                  scenario=scenario, cust_sum=cust_sum[:1500]))


def poc_plan(customer: str, scenario: str, prop_sum: str) -> str:
    return llm(SYS, P_POC.format(customer=customer, scenario=scenario,
                                 prop_sum=prop_sum[:1500]))


def demo_site(customer: str, industry: str, scenario: str, prop_sum: str) -> str:
    html = llm(SYS_DEMO, P_DEMO.format(customer=customer, industry=industry,
                                       scenario=scenario, prop_sum=prop_sum[:1200]),
               max_tokens=4000, temp=0.5)
    m = re.search(r"```(?:html)?\s*(.*?)```", html, re.S)
    if m:
        html = m.group(1)
    return html.strip()
