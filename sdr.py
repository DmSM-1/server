import numpy as np
import adi


class SDR:
    def __init__(
            self, 
            uri='ip:192.168.4.1', 
            fc=2_800_000_000, 
            fs=5_000_000, 
            rf_bandwidth = 5_000_000, 
            buffer_size = 2**16,
            rx_hardwaregain_chan0 = 60,
            tx_hardwaregain_chan0 = -10,
            tx_cycle_buffer = False
        ):
        """Инициализация подключения к PLUTO"""

        self.uri = uri
        self.fc = int(fc)
        self.fs = int(fs)
        self.rf_bandwidth = int(rf_bandwidth)
        self.buffer_size = int(buffer_size)
        self.rx_hardwaregain_chan0 = int(rx_hardwaregain_chan0)
        self.tx_hardwaregain_chan0 = int(tx_hardwaregain_chan0)
        self.tx_cycle_buffer = tx_cycle_buffer

        self.sdr = adi.Pluto(self.uri)    

        self.sdr.rx_lo = self.fc
        self.sdr.tx_lo = self.fc

        self.sdr.sample_rate = self.fs

        self.sdr.rx_rf_bandwidth = self.rf_bandwidth
        self.sdr.tx_rf_bandwidth = self.rf_bandwidth

        self.sdr.rx_buffer_size = self.buffer_size
        self.sdr.tx_buffer_size = self.buffer_size

        self.sdr.gain_control_mode_chan0 = "manual"
        self.sdr.gain_control_mode_chan1 = "manual"
        self.sdr.rx_hardwaregain_chan0 = self.rx_hardwaregain_chan0
        self.sdr.tx_hardwaregain_chan0 = self.tx_hardwaregain_chan0

        self.sdr.tx_cyclic_buffer = self.tx_cycle_buffer


    def send(self, data):
        """Отправить I/Q данные"""
        # import matplotlib.pyplot as plt
        # # plt.plot(np.abs(np.fft.fftshift(np.fft.fft(data))))
        # # plt.show()
        # plt.plot(np.real(data))
        # plt.plot(np.imag(data))
        # plt.show()
        
        self.sdr.tx(data)

        return True
    

    def recv(self):
        """Получить I/Q данные"""
        
        received = self.sdr.rx()
        
        return received.tolist()
    

    def close(self):
        """Закрыть подключение"""

        try:
            self.sdr.rx_destroy_buffer()
            self.sdr.tx_destroy_buffer()
            del self.sdr
        except:
            pass
