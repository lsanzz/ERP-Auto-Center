(function () {
  function onlyDigits(value) {
    return (value || '').replace(/\D/g, '');
  }

  window.setupCepLookup = function (options) {
    const cep = document.getElementById(options.cepId);
    const button = document.getElementById(options.buttonId);
    const status = document.getElementById(options.statusId);
    if (!cep || !button) return;

    async function consultar() {
      const digits = onlyDigits(cep.value);
      if (digits.length !== 8) {
        if (status) status.textContent = 'Informe um CEP com 8 dígitos.';
        return;
      }

      button.disabled = true;
      if (status) status.textContent = 'Consultando CEP...';
      try {
        const response = await fetch(`/api/cep/${digits}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Não foi possível consultar o CEP.');

        cep.value = data.cep || digits.replace(/^(\d{5})(\d{3})$/, '$1-$2');
        if (options.addressId) {
          const address = document.getElementById(options.addressId);
          if (address) {
            address.value = [data.logradouro, data.complemento, data.bairro]
              .filter(Boolean).join(', ');
          }
        }
        if (options.cityId) {
          const city = document.getElementById(options.cityId);
          if (city) city.value = data.localidade || '';
        }
        if (options.stateId) {
          const state = document.getElementById(options.stateId);
          if (state) state.value = data.uf || '';
        }
        if (status) status.textContent = 'Endereço preenchido. Confira o número e complemente se necessário.';
      } catch (error) {
        if (status) status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    }

    button.addEventListener('click', consultar);
    cep.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        consultar();
      }
    });
  };
})();
