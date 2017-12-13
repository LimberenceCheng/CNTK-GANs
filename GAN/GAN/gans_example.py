'''
The original idea was proposed by [Goodfellow et al](https://arxiv.org/pdf/1406.2661v1.pdf) at NIPS  2014. In this tutorial, we show how to use the Cognitive Toolkit to create a basic GAN network for generating synthetic MNIST digits.
'''
import numpy as np
import os
import cntk as C
import cntk.tests.test_utils

cntk.tests.test_utils.set_device_from_pytest_env() # (only needed for our build system)
C.cntk_py.set_fixed_random_seed(1) # fix a random seed for CNTK components

# Ensure the training data is generated and available for this tutorial
# We search in two locations in the toolkit for the cached MNIST data set.

data_found = False
for data_dir in [os.path.join("..", "Examples", "Image", "DataSets", "MNIST"),
                 os.path.join("data", "MNIST")]:
    train_file = os.path.join(data_dir, "Train-28x28_cntk_text.txt")
    if os.path.isfile(train_file):
        data_found = True
        break
        
if not data_found:
    raise ValueError("Please generate the data by completing CNTK 103 Part A")
    
print("Data directory is {0}".format(data_dir))

def create_reader(path, is_training, input_dim, label_dim):
    deserializer = C.io.CTFDeserializer(
        filename = path,
        streams = C.io.StreamDefs(
            labels_unused = C.io.StreamDef(field = 'labels', shape = label_dim, is_sparse = False),
            features = C.io.StreamDef(field = 'features', shape = input_dim, is_sparse = False
            )
        )
    )
    return C.io.MinibatchSource(
        deserializers = deserializer,
        randomize = is_training,
        max_sweeps = C.io.INFINITELY_REPEAT if is_training else 1
    )

np.random.seed(123)
def noise_sample(num_samples):
    return np.random.uniform(
        low = -1.0,
        high = 1.0,
        size = [num_samples, g_input_dim]        
    ).astype(np.float32)

# architectural parameters
g_input_dim = 100
g_hidden_dim = 128
g_output_dim = d_input_dim = 784
d_hidden_dim = 128
d_output_dim = 1

def generator(z):
    with C.layers.default_options(init = C.xavier()):
        h1 = C.layers.Dense(g_hidden_dim, activation = C.relu)(z)
        return C.layers.Dense(g_output_dim, activation = C.tanh)(h1)

def discriminator(x):
    with C.layers.default_options(init = C.xavier()):
        h1 = C.layers.Dense(d_hidden_dim, activation = C.relu)(x)
        return C.layers.Dense(d_output_dim, activation = C.sigmoid)(h1)

# training config
minibatch_size = 1024
num_minibatches = 300 if isFast else 40000
lr = 0.00005

def build_graph(noise_shape, image_shape,
                G_progress_printer, D_progress_printer):
    '''
    The rest of the computational graph is mostly responsible for 
    coordinating the training algorithms and parameter updates, 
    which is particularly tricky with GANs for couple reasons.

    First, the discriminator must be used on both the real MNIST 
    images and fake images generated by the generator function. 
    One way to represent this in the computational graph is to 
    create a clone of the output of the discriminator function, 
    but with substituted inputs. Setting method=share in the 
    clone function ensures that both paths through the 
    discriminator model use the same set of parameters.

    Second, we need to update the parameters for the generator 
    and discriminator model separately using the gradients from 
    different loss functions. We can get the parameters for a 
    Function in the graph with the parameters attribute. However, 
    when updating the model parameters, update only the parameters 
    of the respective models while keeping the other parameters 
    unchanged. In other words, when updating the generator we will 
    update only the parameters of the  GG  function while keeping 
    the parameters of the  DD  function fixed and vice versa.
    '''
    input_dynamic_axes = [C.Axis.default_batch_axis()]
    Z = C.input_variable(noise_shape, dynamic_axes=input_dynamic_axes)
    X_real = C.input_variable(image_shape, dynamic_axes=input_dynamic_axes)
    X_real_scaled = 2*(X_real / 255.0) - 1.0

    # Create the model function for the generator and discriminator models
    X_fake = generator(Z)
    D_real = discriminator(X_real_scaled)
    D_fake = D_real.clone(
        method = 'share',
        substitutions = {X_real_scaled.output: X_fake.output}
    )

    # Create loss functions and configure optimazation algorithms
    G_loss = 1.0 - C.log(D_fake)
    D_loss = -(C.log(D_real) + C.log(1.0 - D_fake))

    G_learner = C.fsadagrad(
        parameters = X_fake.parameters,
        lr = C.learning_parameter_schedule_per_sample(lr),
        momentum = C.momentum_schedule_per_sample(0.9985724484938566)
    )
    D_learner = C.fsadagrad(
        parameters = D_real.parameters,
        lr = C.learning_parameter_schedule_per_sample(lr),
        momentum = C.momentum_schedule_per_sample(0.9985724484938566)
    )

    # Instantiate the trainers
    G_trainer = C.Trainer(
        X_fake,
        (G_loss, None),
        G_learner,
        G_progress_printer
    )
    D_trainer = C.Trainer(
        D_real,
        (D_loss, None),
        D_learner,
        D_progress_printer
    )

    return X_real, X_fake, Z, G_trainer, D_trainer

def train(reader_train):
    k = 2
    
    # print out loss for each model for upto 50 times
    print_frequency_mbsize = num_minibatches // 50
    pp_G = C.logging.ProgressPrinter(print_frequency_mbsize)
    pp_D = C.logging.ProgressPrinter(print_frequency_mbsize * k)

    X_real, X_fake, Z, G_trainer, D_trainer = \
        build_graph(g_input_dim, d_input_dim, pp_G, pp_D)
    
    input_map = {X_real: reader_train.streams.features}
    for train_step in range(num_minibatches):

        # train the discriminator model for k steps
        for gen_train_step in range(k):
            Z_data = noise_sample(minibatch_size)
            X_data = reader_train.next_minibatch(minibatch_size, input_map)
            if X_data[X_real].num_samples == Z_data.shape[0]:
                batch_inputs = {X_real: X_data[X_real].data, 
                                Z: Z_data}
                D_trainer.train_minibatch(batch_inputs)

        # train the generator model for a single step
        Z_data = noise_sample(minibatch_size)
        batch_inputs = {Z: Z_data}
        G_trainer.train_minibatch(batch_inputs)

        G_trainer_loss = G_trainer.previous_minibatch_loss_average

    return Z, X_fake, G_trainer_loss

reader_train = create_reader(train_file, True, d_input_dim, label_dim=10)

G_input, G_output, G_trainer_loss = train(reader_train)