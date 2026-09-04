"""Research skill: customer & industry research documents (gpt-4o)."""
from core import llm

SYS = ("You are a senior industry advisor on the Microsoft Azure solutions team. "
       "Write formal, well-structured Markdown documents in English, ready to hand "
       "to a sales team. Base answers on your knowledge; never fabricate precise "
       "figures — mark uncertain items as [TBC]. Output the document body directly, "
       "starting with a level-1 heading. No pleasantries.")

P_CUST = ("Write a 'Customer Research Report' for the customer below, covering: "
          "company overview; core businesses and segments; current digital/IT and "
          "cloud adoption; strategic direction and recent moves; business pain "
          "points and digitalization opportunities; key stakeholder personas "
          "(CIO / R&D / business); recommended Azure engagement angles.\n"
          "Customer: {customer}\nIndustry: {industry}\nContext: {scenario}")

P_IND = ("Write an 'Industry Research Report' for the industry below (China market "
         "focus), covering: market size and trends; a landscape of typical AI / "
         "generative-AI use cases; data compliance and regulatory requirements "
         "(e.g. MLPS, GxP / NMPA where applicable); key players and competitive "
         "landscape; cloud & AI adoption status; five talking points for sellers.\n"
         "Industry: {industry}\nReference customer: {customer}")


def customer_research(customer: str, industry: str, scenario: str) -> str:
    return llm(SYS, P_CUST.format(customer=customer, industry=industry,
                                  scenario=scenario))


def industry_research(customer: str, industry: str) -> str:
    return llm(SYS, P_IND.format(industry=industry, customer=customer))
