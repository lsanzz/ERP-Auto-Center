"""Local structural validation before UniNFe supplies the XML signature."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from lxml import etree

SCHEMAS = Path(__file__).parent / 'schemas' / 'nfe'
XS = {'xs': 'http://www.w3.org/2001/XMLSchema'}


class LocalSchemas(etree.Resolver):
    def resolve(self, url, public_id, context):
        parsed = urlsplit(url)
        if parsed.scheme == 'file':
            if parsed.netloc:
                raise ValueError('Schema remoto não permitido.')
            path = Path(url2pathname(parsed.path)).resolve()
        else:
            path = Path(url).resolve()
        if path.parent != SCHEMAS.resolve() or path.suffix != '.xsd':
            raise ValueError('Referência de schema fora do pacote fiscal local.')
        data = path.read_bytes()
        if path.name == 'leiauteNFe_v4.00.xsd':
            tree = etree.fromstring(data)
            # Only TNFe's outer signature is optional in this pre-signing pass.
            # Original bundled files remain intact. UniNFe must sign and perform
            # the final, unmodified schema validation before transmission.
            signatures = tree.xpath("xs:complexType[@name='TNFe']/xs:sequence/xs:element[@ref='ds:Signature']", namespaces=XS)
            if len(signatures) != 1:
                raise ValueError('Estrutura inesperada do schema TNFe.')
            signatures[0].set('minOccurs', '0')
            data = etree.tostring(tree)
        return self.resolve_string(data, context, base_url=path.as_uri())


@lru_cache(maxsize=1)
def unsigned_schema():
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    parser.resolvers.add(LocalSchemas())
    return etree.XMLSchema(etree.parse(str(SCHEMAS / 'nfe_v4.00.xsd'), parser))


def validate_unsigned(xml):
    data = xml.encode('utf-8') if isinstance(xml, str) else xml
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('DTD não é permitido em XML fiscal.')
    try:
        unsigned_schema().assertValid(root)
    except etree.DocumentInvalid as exc:
        raise ValueError(f'XML fiscal fora do leiaute: {exc.error_log.last_error.message}') from exc
