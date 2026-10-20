# Schemas NF-e 4.00

Obtidos sem alteração do repositório do fornecedor UniNFe/Unimake DFe:
https://github.com/Unimake/DFe/tree/993447a42415c623ff91b567da2af8cd51706810/source/.NET%20Standard/Unimake.Business.DFe/Xml/Schemas/NFe

Revisão fixada: `993447a42415c623ff91b567da2af8cd51706810`.
Incluídos apenas o schema raiz da NF-e e suas dependências diretas.

`uninfe_schema.py` valida o XML antes da assinatura. Apenas a obrigatoriedade
da assinatura externa de TNFe é relaxada em memória nessa etapa. Nenhum arquivo
XSD é alterado; UniNFe realiza assinatura e validação final com o schema integral.
Validade estrutural não comprova regras de negócio nem autorização da SEFAZ.
